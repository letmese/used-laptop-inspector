"""What speed capability does the wired NIC advertise?"""

import sys

sys.path.insert(0, ".")

from laptop_inspector.engine import powershell as ps

print("--- adapters ---")
print(ps._run(r"""
Get-NetAdapter -Physical -ErrorAction SilentlyContinue |
  Where-Object { $_.PhysicalMediaType -eq '802.3' } |
  ForEach-Object {
    "name=$($_.Name) desc=$($_.InterfaceDescription) status=$($_.Status) " +
    "link=$($_.LinkSpeed) speed=$($_.Speed) full=$($_.FullDuplex)"
  }
"""))

print("--- speed/duplex capability list ---")
print(ps._run(r"""
$nic = Get-NetAdapter -Physical -ErrorAction SilentlyContinue |
  Where-Object { $_.PhysicalMediaType -eq '802.3' } | Select-Object -First 1
if ($nic) {
  $prop = Get-NetAdapterAdvancedProperty -Name $nic.Name -ErrorAction SilentlyContinue |
    Where-Object { $_.RegistryKeyword -match 'SpeedDuplex|\*SpeedDuplex' } |
    Select-Object -First 1
  if ($prop) {
    "keyword=$($prop.RegistryKeyword)"
    "current=$($prop.DisplayValue)"
    "valid=" + ($prop.ValidDisplayValues -join ' | ')
  } else {
    "no speed/duplex property"
  }
} else { "no 802.3 adapter" }
"""))
