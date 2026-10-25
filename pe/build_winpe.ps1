<#
.SYNOPSIS
    Builds a bootable WinPE image containing Used Laptop Inspector.

.DESCRIPTION
    Boots from USB, runs the scan with no operating system of the seller's
    involved, and writes the report back to the stick.

    Requires the Windows ADK (Deployment Tools + Windows Preinstallation
    Environment) installed on the machine running this script. That is a ~3 GB
    download from Microsoft and cannot be automated from here.

    Run this in an elevated PowerShell.

.EXAMPLE
    .\build_winpe.ps1 -UsbDrive E
#>

param(
    [string]$WorkDir = "C:\WinPE_uli",
    [string]$IsoPath = "C:\uli-pe.iso",
    # Optional: write straight to a USB stick instead of an ISO. THIS ERASES IT.
    [string]$UsbDrive = ""
)

$ErrorActionPreference = "Stop"

function Fail($message) {
    Write-Host ""
    Write-Host "  $message" -ForegroundColor Red
    Write-Host ""
    exit 1
}

# --- locate the ADK ---------------------------------------------------------
$adk = "${env:ProgramFiles(x86)}\Windows Kits\10\Assessment and Deployment Kit"
if (-not (Test-Path $adk)) {
    $adk = "$env:ProgramFiles\Windows Kits\10\Assessment and Deployment Kit"
}
if (-not (Test-Path $adk)) {
    Fail "Windows ADK not found. Install 'Deployment Tools' and 'Windows Preinstallation Environment' from https://aka.ms/adk"
}

$peOc = Join-Path $adk "Windows Preinstallation Environment\amd64\WinPE_OCs"
$copype = Join-Path $adk "Deployment Tools\amd64\DISM\copype.cmd"
$makeMedia = Join-Path $adk "Deployment Tools\amd64\DISM\MakeWinPEMedia.cmd"

foreach ($path in @($peOc, $copype, $makeMedia)) {
    if (-not (Test-Path $path)) { Fail "Missing from the ADK: $path" }
}

# --- the exe this image will run -------------------------------------------
$repo = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $repo "dist_pe\UsedLaptopInspectorPE.exe"
if (-not (Test-Path $exe)) {
    Fail "Build the headless exe first:  pyinstaller build_pe.spec --noconfirm --distpath dist_pe"
}

Write-Host ""
Write-Host "  ADK     : $adk"
Write-Host "  exe     : $exe"
Write-Host "  workdir : $WorkDir"
Write-Host ""

# --- copy the base image ----------------------------------------------------
if (Test-Path $WorkDir) { Remove-Item $WorkDir -Recurse -Force }
& $copype amd64 $WorkDir | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "copype failed" }

$wim = Join-Path $WorkDir "media\sources\boot.wim"
$mount = Join-Path $WorkDir "mount"

Write-Host "  Mounting boot.wim..."
Dism /Mount-Image /ImageFile:"$wim" /Index:1 /MountDir:"$mount" | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "could not mount boot.wim" }

try {
    # WMI and PowerShell are optional components. Without WinPE-WMI every
    # Get-CimInstance in the scan returns nothing and the report is empty -
    # this is the single most important step in the whole script.
    Write-Host "  Adding WMI, PowerShell and Scripting..."
    foreach ($oc in @("WinPE-WMI", "WinPE-PowerShell", "WinPE-Scripting",
                      "WinPE-NetFx", "WinPE-DismCmdlets")) {
        $package = Join-Path $peOc "$oc.cmd"
        if (Test-Path $package) {
            Dism /Image:"$mount" /Add-Package /PackagePath:"$package" | Out-Null
        } else {
            Write-Host "    (skipped $oc - not in this ADK)"
        }
    }

    Write-Host "  Copying the scanner..."
    $tools = Join-Path $mount "Tools\uli"
    New-Item -ItemType Directory -Path $tools -Force | Out-Null
    Copy-Item $exe $tools
    Copy-Item (Join-Path $PSScriptRoot "startnet.cmd") (Join-Path $mount "Windows\System32\startnet.cmd") -Force
}
finally {
    Write-Host "  Committing..."
    Dism /Unmount-Image /MountDir:"$mount" /Commit | Out-Null
}

# --- produce media ----------------------------------------------------------
if ($UsbDrive) {
    Write-Host ""
    Write-Host "  Writing to USB drive $UsbDrive`: THIS ERASES IT." -ForegroundColor Yellow
    Start-Sleep -Seconds 5
    & $makeMedia /UFD $WorkDir "${UsbDrive}:" | Out-Null
    Write-Host "  Done. Boot the target laptop from that stick." -ForegroundColor Green
}
else {
    & $makeMedia /ISO $WorkDir $IsoPath | Out-Null
    Write-Host ""
    Write-Host "  ISO written to $IsoPath" -ForegroundColor Green
    Write-Host "  Write it to a USB stick with Rufus, or run this again with -UsbDrive E"
}

Write-Host ""
