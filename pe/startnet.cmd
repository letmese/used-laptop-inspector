@echo off
REM ---------------------------------------------------------------------------
REM  Startup script for the Used Laptop Inspector WinPE image.
REM
REM  wpeinit must run first: it starts the WMI service, and every hardware query
REM  in this tool goes through WMI. Skip it and the scan reports an empty machine.
REM ---------------------------------------------------------------------------

wpeinit

set ULI_PE=1

REM The stick is X: while WinPE is running, so the tool lives at X:\Tools\uli.
REM Reports are written back to the same folder - pull the stick out and the
REM results come with it.
cd /d X:\Tools\uli

if not exist UsedLaptopInspectorPE.exe (
    echo.
    echo   UsedLaptopInspectorPE.exe is missing from X:\Tools\uli
    echo.
    goto :done
)

UsedLaptopInspectorPE.exe

:done
echo.
echo   Scan finished. Reports are in X:\Tools\uli\reports
echo   Type EXIT to close the command prompt, then remove the USB stick.
echo.
