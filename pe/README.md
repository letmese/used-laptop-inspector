# Booting without the seller's Windows

The scanner is designed to run twice: once as the desktop app, and once from a
WinPE image you boot yourself. The second mode is the one that answers "is this
laptop what the seller says it is" without trusting the laptop's own operating
system.

## Why it matters

When you run the app on the seller's Windows, every number comes from that
Windows. A tampered install can lie: a spoofed CPU string in the registry, a
rootkit hiding a failing drive, a shimmed SMART tool reporting a healthy disk.
Boot your own image and none of that code is running - the scan talks to the
firmware and the hardware directly.

## What you get, and what you do not

| Check | In WinPE | Why |
|---|---|---|
| CPU, RAM, board, BIOS | yes | SMBIOS, read straight from firmware |
| Storage SMART | **best case** | nothing else is holding the disk, so raw device access is cleaner than on a running Windows |
| Battery | usually | depends on whether the image exposes the battery driver |
| Thermal / throttling | usually | ACPI thermal zones, when present |
| Discrete GPU presence | yes | PnP and PCI enumeration |
| **GPU load test** | **no** | needs D3D11; WinPE has no GPU driver stack |
| **Screen / keyboard / port tests** | **no** | they are interactive dialogs; the PE build has no GUI |
| Radios & peripherals | **unreliable** | WinPE enumerates only devices whose drivers are in the image, so "not fitted" there means "not visible", not "missing". The report says so. |

Two things this cannot protect you from:

* **Firmware lies.** SMBIOS and ACPI come from the BIOS. Someone who reflashes
  it can still change what the machine claims to be.
* **SMART reset.** Some drives accept a vendor command that clears the attribute
  table. A wiped SMART history looks like a new drive.

So: it removes the *operating system* from the list of things that can lie. It
does not make the hardware itself trustworthy.

## Building the image

You need the **Windows ADK** - Deployment Tools and Windows Preinstallation
Environment - from <https://aka.ms/adk>. That is a ~3 GB install and it has to
come from Microsoft.

```powershell
# 1. build the headless exe (no Qt, ~10 MB)
pyinstaller build_pe.spec --noconfirm --distpath dist_pe

# 2. assemble the boot image (elevated PowerShell)
.\pe\build_winpe.ps1 -IsoPath C:\uli-pe.iso

# or write straight to a stick - this erases it
.\pe\build_winpe.ps1 -UsbDrive E
```

The script adds **WinPE-WMI**, **WinPE-PowerShell**, **WinPE-Scripting**,
**WinPE-NetFx** and **WinPE-DismCmdlets**, copies the exe to `X:\Tools\uli`, and
installs `startnet.cmd` so the scan runs on boot.

The WMI component is not optional. Without it every `Get-CimInstance` returns
nothing and the report comes back as an empty machine - that is the single most
common way a WinPE build fails.

## On the laptop

1. Boot from the stick (F12 / F9 at power-on, varies by vendor).
2. It scans automatically. Takes about a minute.
3. The report lands in `X:\Tools\uli\reports\` - on the stick, so it leaves with
   you: JSON, HTML and a one-page PDF.

## Status

The headless exe is built and verified: it runs a full scan and writes all three
reports. The WinPE image itself has **not** been built or booted here, because
that needs the ADK. Treat `build_winpe.ps1` as reviewed but unproven until you
run it once.
