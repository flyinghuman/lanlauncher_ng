param(
    [string]$ManifestPath = "tools/manifest.json",
    [string]$RepoRoot = "."
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-CurrentToolPlatform {
    if ($env:OS -eq "Windows_NT") {
        return "windows-amd64"
    }

    $runtime = [System.Runtime.InteropServices.RuntimeInformation]
    if ($runtime::IsOSPlatform([System.Runtime.InteropServices.OSPlatform]::Linux)) {
        return "linux-x64"
    }

    return ""
}

if (-not (Test-Path $ManifestPath)) {
    throw "Manifest not found: $ManifestPath"
}

$manifest = Get-Content $ManifestPath -Raw | ConvertFrom-Json
if (-not ($manifest.PSObject.Properties.Name -contains "tools")) {
    throw "Invalid manifest: missing 'tools' array"
}

$failures = @()
$currentPlatform = Get-CurrentToolPlatform

foreach ($tool in $manifest.tools) {
    $toolPlatform = [string]$tool.platform
    if (-not [string]::IsNullOrWhiteSpace($toolPlatform) -and $toolPlatform -ne "any" -and -not [string]::IsNullOrWhiteSpace($currentPlatform) -and $toolPlatform -ne $currentPlatform) {
        continue
    }

    # Resolve the bundled binary path relative to repository root.
    $filePath = Join-Path $RepoRoot $tool.path

    if (-not (Test-Path $filePath)) {
        $failures += "Missing file: $($tool.name) -> $filePath"
        continue
    }

    $hash = (Get-FileHash -Path $filePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne $tool.sha256.ToLowerInvariant()) {
        $failures += "Checksum mismatch: $($tool.name) expected=$($tool.sha256) actual=$hash"
    }

    $licensePath = Join-Path $RepoRoot $tool.license_file
    if (-not (Test-Path $licensePath)) {
        $failures += "Missing license file: $($tool.name) -> $licensePath"
    }
}

if ($failures.Count -eq 0) {
    Write-Host "OK: bundled tool manifest verification passed."
    exit 0
}

Write-Error "Bundled tool verification failed."
$failures | ForEach-Object { Write-Host "  - $_" }
exit 1
