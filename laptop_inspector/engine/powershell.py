"""PowerShell / CIM collectors.

One process spawn per group of facts, not one per property - on a 2011 quad-core
a `powershell.exe` start costs ~400 ms and we are not paying that thirty times.

Everything returns a dict. Missing data is an empty value, never an exception.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

CREATE_NO_WINDOW = 0x08000000
PS = "powershell.exe"

_PRELUDE = (
    "$ErrorActionPreference='SilentlyContinue';"
    "$ProgressPreference='SilentlyContinue';"
    "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
)


def _run(script: str, timeout: float = 45.0) -> str:
    try:
        proc = subprocess.run(
            [PS, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", _PRELUDE + script],
            capture_output=True, timeout=timeout, creationflags=CREATE_NO_WINDOW,
        )
        return proc.stdout.decode("utf-8", "replace").strip()
    except Exception:
        return ""


def _run_json(script: str, timeout: float = 45.0) -> Any:
    raw = _run(script, timeout=timeout)
    if not raw:
        return None
    # strip anything the profile may have printed before the JSON
    for start in ("{", "["):
        idx = raw.find(start)
        if idx >= 0:
            raw = raw[idx:]
            break
    try:
        return json.loads(raw)
    except Exception:
        return None


def as_list(value: Any) -> List[Dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    if isinstance(value, dict):
        return [value]
    return []


# --------------------------------------------------------------------------
# 1. hardware facts
# --------------------------------------------------------------------------
_FACTS_SCRIPT = r"""
$cs   = Get-CimInstance Win32_ComputerSystem
$bios = Get-CimInstance Win32_BIOS
$bb   = Get-CimInstance Win32_BaseBoard
$csp  = Get-CimInstance Win32_ComputerSystemProduct
$cpu  = Get-CimInstance Win32_Processor | Select-Object -First 1
$os   = Get-CimInstance Win32_OperatingSystem
$mem  = Get-CimInstance Win32_PhysicalMemory
$marr = Get-CimInstance Win32_PhysicalMemoryArray | Select-Object -First 1
$gpu  = Get-CimInstance Win32_VideoController
$batt = Get-CimInstance Win32_Battery
$bsd  = Get-CimInstance -Namespace 'root\wmi' -ClassName BatteryStaticData
$bfc  = Get-CimInstance -Namespace 'root\wmi' -ClassName BatteryFullChargedCapacity
$bcc  = Get-CimInstance -Namespace 'root\wmi' -ClassName BatteryCycleCount
$bst  = Get-CimInstance -Namespace 'root\wmi' -ClassName BatteryStatus
$pdisk= Get-CimInstance -Namespace 'root\Microsoft\Windows\Storage' -ClassName MSFT_PhysicalDisk
$ldisk= Get-CimInstance Win32_DiskDrive
$mon  = Get-CimInstance -Namespace 'root\wmi' -ClassName WmiMonitorID
$pnpdisp = Get-PnpDevice -Class Display -ErrorAction SilentlyContinue

[pscustomobject]@{
  system = [pscustomobject]@{
    manufacturer = $cs.Manufacturer
    model        = $cs.Model
    system_family= $cs.SystemFamily
    sku          = $cs.SystemSKUNumber
    total_ram    = $cs.TotalPhysicalMemory
    pc_type      = $cs.PCSystemType
  }
  product = [pscustomobject]@{
    name    = $csp.Name
    version = $csp.Version
    vendor  = $csp.Vendor
    uuid    = $csp.UUID
    ident   = $csp.IdentifyingNumber
  }
  bios = [pscustomobject]@{
    version      = $bios.SMBIOSBIOSVersion
    manufacturer = $bios.Manufacturer
    release_date = $bios.ReleaseDate
    serial       = $bios.SerialNumber
  }
  board = [pscustomobject]@{
    manufacturer = $bb.Manufacturer
    product      = $bb.Product
    version      = $bb.Version
    serial       = $bb.SerialNumber
  }
  cpu = [pscustomobject]@{
    name        = $cpu.Name
    cores       = $cpu.NumberOfCores
    threads     = $cpu.NumberOfLogicalProcessors
    max_mhz     = $cpu.MaxClockSpeed
    socket      = $cpu.SocketDesignation
    tdp_hint    = $cpu.ThermalDesignPower
    l3          = $cpu.L3CacheSize
    virtualization = $cpu.VirtualizationFirmwareEnabled
    description = $cpu.Description
  }
  os = [pscustomobject]@{
    caption      = $os.Caption
    version      = $os.Version
    build        = $os.BuildNumber
    arch         = $os.OSArchitecture
    install_date = $os.InstallDate
    last_boot    = $os.LastBootUpTime
    serial       = $os.SerialNumber
  }
  memory_modules = @($mem | ForEach-Object {
    [pscustomobject]@{
      bank       = $_.DeviceLocator
      capacity   = $_.Capacity
      speed      = $_.Speed
      configured = $_.ConfiguredClockSpeed
      manufacturer = $_.Manufacturer
      part       = $_.PartNumber
      memory_type= $_.SMBIOSMemoryType
      form       = $_.FormFactor
    }
  })
  memory_array = [pscustomobject]@{
    slots        = $marr.MemoryDevices
    max_capacity = $marr.MaxCapacityEx
  }
  gpus = @($gpu | ForEach-Object {
    [pscustomobject]@{
      name        = $_.Name
      vram        = $_.AdapterRAM
      driver_ver  = $_.DriverVersion
      driver_date = $_.DriverDate
      status      = $_.Status
      error_code  = $_.ConfigManagerErrorCode
      pnp_id      = $_.PNPDeviceID
      width       = $_.CurrentHorizontalResolution
      height      = $_.CurrentVerticalResolution
      refresh     = $_.CurrentRefreshRate
      video_mode  = $_.VideoModeDescription
    }
  })
  batteries = @($batt | ForEach-Object {
    [pscustomobject]@{
      name        = $_.Name
      status      = $_.BatteryStatus
      design      = $_.DesignCapacity
      full        = $_.FullChargeCapacity
      chemistry   = $_.Chemistry
      estimated   = $_.EstimatedChargeRemaining
      device_id   = $_.DeviceID
    }
  })
  battery_static = @($bsd | ForEach-Object {
    [pscustomobject]@{
      designed_capacity = $_.DesignedCapacity
      full_capacity     = $_.FullChargedCapacity
      device_name       = $_.DeviceName
      manufacturer      = $_.ManufactureName
      manufacture_date  = $_.ManufactureDate
      serial            = $_.SerialNumber
      chemistry         = $_.Chemistry
      unique_id         = $_.UniqueID
    }
  })
  battery_full = @($bfc | ForEach-Object { [pscustomobject]@{ full = $_.FullChargedCapacity } })
  battery_cycles = @($bcc | ForEach-Object { [pscustomobject]@{ cycles = $_.CycleCount } })
  battery_status = @($bst | ForEach-Object {
    [pscustomobject]@{ remaining = $_.RemainingCapacity; voltage = $_.Voltage; power_online = $_.PowerOnline }
  })
  physical_disks = @($pdisk | ForEach-Object {
    [pscustomobject]@{
      device_id   = $_.DeviceId
      friendly    = $_.FriendlyName
      serial      = $_.SerialNumber
      media       = $_.MediaType
      bus         = $_.BusType
      size        = $_.Size
      health      = $_.HealthStatus
      spindle     = $_.SpindleSpeed
      firmware    = $_.FirmwareVersion
    }
  })
  disk_drives = @($ldisk | ForEach-Object {
    [pscustomobject]@{
      model     = $_.Model
      serial    = $_.SerialNumber
      size      = $_.Size
      interface = $_.InterfaceType
      media     = $_.MediaType
      firmware  = $_.FirmwareRevision
      partitions= $_.Partitions
    }
  })
  monitors = @($mon | ForEach-Object {
    [pscustomobject]@{
      manufacturer = ($_.ManufacturerName | ForEach-Object { [char]$_ }) -join ''
      name         = ($_.UserFriendlyName | ForEach-Object { [char]$_ }) -join ''
      year         = $_.YearOfManufacture
      week         = $_.WeekOfManufacture
    }
  })
  pnp_display = @($pnpdisp | ForEach-Object {
    [pscustomobject]@{
      name     = $_.FriendlyName
      status   = "$($_.Status)"
      problem  = "$($_.Problem)"
      instance = $_.InstanceId
      class    = $_.Class
    }
  })
} | ConvertTo-Json -Depth 6 -Compress
"""


def collect_facts(timeout: float = 60.0) -> Dict[str, Any]:
    data = _run_json(_FACTS_SCRIPT, timeout=timeout)
    return data if isinstance(data, dict) else {}


# --------------------------------------------------------------------------
# 2. TDR / display driver crash history
# --------------------------------------------------------------------------
_TDR_SCRIPT = r"""
$cut = (Get-Date).AddDays(-180)
$providers = 'Display', 'nvlddmkm', 'amdkmdag', 'igfx', 'igfxn', 'atikmdag'
# Filter by ID inside the query, not afterwards: pulling every System event from
# six months of log is what made this the slowest step in the whole scan.
$evts = Get-WinEvent -FilterHashtable @{LogName='System'; Id=13,14,4101,4104; StartTime=$cut} -ErrorAction SilentlyContinue
$tdr = @($evts | Where-Object { $_.Id -eq 4101 -or $providers -contains $_.ProviderName })
$crash = @(Get-WinEvent -FilterHashtable @{LogName='System'; Id=41,6008; StartTime=$cut} -ErrorAction SilentlyContinue)
$list = @($tdr | ForEach-Object {
  [pscustomobject]@{
    time     = $_.TimeCreated.ToString('s')
    id       = $_.Id
    provider = $_.ProviderName
    level    = $_.LevelDisplayName
    message  = ($_.Message -replace '\s+', ' ')
  }
})
[pscustomobject]@{
  tdr_count   = $list.Count
  events      = @($list | Select-Object -First 15)
  unexpected_shutdowns = $crash.Count
  total_events_seen = @($evts).Count
} | ConvertTo-Json -Depth 5 -Compress
"""


def collect_tdr_events(timeout: float = 60.0) -> Dict[str, Any]:
    data = _run_json(_TDR_SCRIPT, timeout=timeout)
    return data if isinstance(data, dict) else {}


# --------------------------------------------------------------------------
# 3. licensing / security posture
# --------------------------------------------------------------------------
_LICENSE_SCRIPT = r"""
$appId = '55c92734-d682-4d71-983e-d6ec3f16059f'
$sl = Get-CimInstance SoftwareLicensingProduct -Property Name,LicenseStatus,ProductKeyChannel,PartialProductKey,ApplicationID,DiscoveredKeyManagementServiceMachineName -Filter "PartialProductKey IS NOT NULL" |
      Where-Object { $_.ApplicationID -eq $appId } | Select-Object -First 1
$bl = Get-CimInstance -Namespace 'root\cimv2\security\microsoftvolumeencryption' -ClassName Win32_EncryptableVolume
$sb = Confirm-SecureBootUEFI
$fw = Get-CimInstance -Namespace 'root\SecurityCenter2' -ClassName FirewallProduct
[pscustomobject]@{
  license_name   = $sl.Name
  license_status = $sl.LicenseStatus
  license_channel= $sl.ProductKeyChannel
  partial_key    = $sl.PartialProductKey
  kms_server     = $sl.DiscoveredKeyManagementServiceMachineName
  bitlocker      = @($bl | ForEach-Object { [pscustomobject]@{ drive = $_.DriveLetter; protection = $_.ProtectionStatus } })
  secure_boot    = $sb
  firmware_type  = $env:firmware_type
  antivirus      = @($fw | ForEach-Object { $_.displayName })
} | ConvertTo-Json -Depth 5 -Compress
"""


def collect_license(timeout: float = 40.0) -> Dict[str, Any]:
    data = _run_json(_LICENSE_SCRIPT, timeout=timeout)
    return data if isinstance(data, dict) else {}


# --------------------------------------------------------------------------
# 4. thermal zones (often absent on consumer laptops - that is fine)
# --------------------------------------------------------------------------
def collect_thermal_zones(timeout: float = 30.0) -> List[float]:
    raw = _run(
        r"Get-CimInstance -Namespace 'root\wmi' -ClassName MSAcpi_ThermalZoneTemperature "
        r"| ForEach-Object { [math]::Round(($_.CurrentTemperature / 10.0) - 273.15, 1) }",
        timeout=timeout,
    )
    out: List[float] = []
    for line in raw.splitlines():
        line = line.strip()
        try:
            val = float(line)
        except ValueError:
            continue
        if -20 < val < 130:
            out.append(round(val, 1))
    return out


# --------------------------------------------------------------------------
# 5. Radios, cameras and the things a seller forgets to mention
# --------------------------------------------------------------------------
_PERIPHERAL_SCRIPT = r"""
# One enumeration, filtered in memory. Eight separate Get-PnpDevice -Class calls
# cost eight WMI round trips and made this the slowest collector in the scan.
$all = @(Get-PnpDevice -ErrorAction SilentlyContinue)

function dev($classes) {
  @($all | Where-Object { $classes -contains "$($_.Class)" } | ForEach-Object {
    [pscustomobject]@{
      name     = $_.FriendlyName
      status   = "$($_.Status)"
      problem  = "$($_.Problem)"
      instance = $_.InstanceId
      class    = "$($_.Class)"
    }
  })
}

$adapters = @(Get-NetAdapter -ErrorAction SilentlyContinue | ForEach-Object {
  # A wired NIC reports 0 bps when no cable is in, so the negotiated link tells
  # us nothing about what the port can do. The speed/duplex capability list does.
  $speedValid = ''
  if ("$($_.PhysicalMediaType)" -eq '802.3') {
    try {
      $prop = Get-NetAdapterAdvancedProperty -Name $_.Name -ErrorAction SilentlyContinue |
        Where-Object { "$($_.RegistryKeyword)" -like '*SpeedDuplex*' } |
        Select-Object -First 1
      if ($prop) { $speedValid = ($prop.ValidDisplayValues -join '|') }
    } catch { }
  }
  [pscustomobject]@{
    name        = $_.Name
    description = $_.InterfaceDescription
    status      = "$($_.Status)"
    link        = "$($_.LinkSpeed)"
    media       = "$($_.MediaType)"
    physical    = "$($_.PhysicalMediaType)"
    mac         = $_.MacAddress
    speed_valid = $speedValid
  }
})

# Which 802.11 amendments the driver claims. The tokens are ASCII protocol
# names, so this survives a non-English Windows where the labels are localised.
# Note 802.11w is management-frame protection, not a generation - the caller
# maps only be/ax/ac/n to WiFi 7/6/5/4.
$drv = (netsh wlan show drivers 2>$null) -join ' '
$standards = @([regex]::Matches($drv, '802\.11[a-z]+') | ForEach-Object { $_.Value } | Sort-Object -Unique)

# Bluetooth spec version, where the stack exposes it. Often absent, in which
# case the caller falls back to identifying the controller by name.
$bt = @($all | Where-Object { "$($_.Class)" -eq 'Bluetooth' } | ForEach-Object {
  $version = ''
  try {
    $prop = Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName 'DEVPKEY_Bluetooth_Radio_Version' -ErrorAction SilentlyContinue
    if ($prop) { $version = "$($prop.Data)" }
  } catch { }
  [pscustomobject]@{
    name     = $_.FriendlyName
    status   = "$($_.Status)"
    problem  = "$($_.Problem)"
    instance = $_.InstanceId
    class    = "$($_.Class)"
    version  = $version
  }
})

[pscustomobject]@{
  adapters  = $adapters
  standards = $standards
  net       = dev 'Net'
  bluetooth = $bt
  camera    = dev 'Camera','Image'
  modem     = dev 'Modem'
  audio     = dev 'AudioEndpoint','MEDIA'
  smartcard = dev 'SmartCardReader'
  sdhost    = dev 'SDHost'
  biometric = dev 'Biometric'
} | ConvertTo-Json -Depth 6 -Compress
"""


def collect_peripherals(timeout: float = 45.0) -> Dict[str, Any]:
    """WiFi, Bluetooth, camera, Ethernet, modem, card reader, fingerprint.

    Presence and driver state only. A WiFi link cannot be proven working without
    a network to join, so this reports what Windows sees and says so rather than
    pretending a connection test happened.
    """
    data = _run_json(_PERIPHERAL_SCRIPT, timeout=timeout)
    return data if isinstance(data, dict) else {}


# --------------------------------------------------------------------------
# 6. powercfg battery report
# --------------------------------------------------------------------------
def battery_report_xml(timeout: float = 60.0) -> Dict[str, Any]:
    """`powercfg /batteryreport` is the one native source that reliably carries
    design capacity, full-charge capacity and cycle count together."""
    path = os.path.join(tempfile.gettempdir(), "uli_battery_report.xml")
    try:
        if os.path.exists(path):
            os.remove(path)
        subprocess.run(
            ["powercfg", "/batteryreport", "/output", path, "/xml"],
            capture_output=True, timeout=timeout, creationflags=CREATE_NO_WINDOW,
        )
        if not os.path.exists(path):
            return {}
        tree = ET.parse(path)
        root = tree.getroot()
        out: Dict[str, Any] = {"batteries": []}
        info = root.find("ReportInformation")
        if info is not None:
            scan = info.findtext("ScanTime")
            if scan:
                out["scan_time"] = scan
        for bat in root.iter("Battery"):
            def f(name: str) -> Optional[str]:
                el = bat.find(name)
                return el.text if el is not None else None

            def num(name: str) -> Optional[int]:
                v = f(name)
                try:
                    return int(v) if v not in (None, "") else None
                except ValueError:
                    return None

            out["batteries"].append({
                "id": f("Id"),
                "manufacturer": f("Manufacturer"),
                "serial": f("SerialNumber"),
                "chemistry": f("Chemistry"),
                "design_capacity": num("DesignCapacity"),
                "full_charge_capacity": num("FullChargeCapacity"),
                "cycle_count": num("CycleCount"),
                "long_term": f("LongTerm"),
            })
        return out
    except Exception:
        return {}
    finally:
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
