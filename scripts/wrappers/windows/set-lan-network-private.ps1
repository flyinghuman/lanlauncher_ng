param(
    [switch]$Elevated
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin -and -not $Elevated) {
    try {
        $currentScript = $MyInvocation.MyCommand.Path
        $argList = @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", "`"$currentScript`"",
            "-Elevated"
        )
        $proc = Start-Process -FilePath "powershell.exe" -ArgumentList $argList -Verb RunAs -PassThru -Wait
        exit $proc.ExitCode
    } catch {
        Write-Error "admin_prompt_cancelled"
        exit 1
    }
}

if (-not $isAdmin) {
    Write-Error "admin_required"
    exit 1
}

$profiles = Get-NetConnectionProfile | Where-Object {
    $_.NetworkCategory -eq "Public" -and ($_.IPv4Connectivity -ne "Disconnected" -or $_.IPv6Connectivity -ne "Disconnected")
}

if ($null -eq $profiles -or $profiles.Count -eq 0) {
    Write-Output "no_public_profiles_found"
    exit 0
}

$changed = 0
foreach ($profile in $profiles) {
    # Some LAN games rely on Private profile discovery behavior.
    Set-NetConnectionProfile -InterfaceIndex $profile.InterfaceIndex -NetworkCategory Private
    $changed++
}

Write-Output ("profiles_switched_private:{0}" -f $changed)
