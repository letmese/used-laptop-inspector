"""What standards does the WiFi driver claim, and can we read a BT version?"""

import sys

sys.path.insert(0, ".")

from laptop_inspector.engine import powershell as ps

print("--- radio standards from the driver ---")
print(ps._run(r"""
$drv = (netsh wlan show drivers 2>$null) -join ' '
$std = @([regex]::Matches($drv, '802\.11\w+') | ForEach-Object { $_.Value } | Sort-Object -Unique)
"tokens=" + ($std -join ',')
"""))

print("--- bluetooth radio version property, if the stack exposes it ---")
print(ps._run(r"""
$bt = Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue
foreach ($d in $bt) {
  $v = (Get-PnpDeviceProperty -InstanceId $d.InstanceId -KeyName 'DEVPKEY_Bluetooth_Radio_Version' -ErrorAction SilentlyContinue).Data
  "name=$($d.FriendlyName) status=$($d.Status) version=$v"
}
if (-not $bt) { "no bluetooth devices" }
"""))

print("--- adapter names for the wifi card ---")
print(ps._run(r"""
Get-NetAdapter -Physical -ErrorAction SilentlyContinue |
  Where-Object { $_.PhysicalMediaType -like '*802.11*' } |
  ForEach-Object { "name=$($_.InterfaceDescription) link=$($_.LinkSpeed)" }
"""))
