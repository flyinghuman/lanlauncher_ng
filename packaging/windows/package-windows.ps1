param(
    [string]$OutputRoot = "dist/windows/lanlauncherng"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

powershell -ExecutionPolicy Bypass -File "tools/scripts/package-windows.ps1" -OutputRoot $OutputRoot
