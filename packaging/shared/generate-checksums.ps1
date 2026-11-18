param(
    [string]$DistRoot = "dist"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not (Test-Path $DistRoot)) {
    throw "Distribution folder not found: $DistRoot"
}

$sumFile = Join-Path $DistRoot "SHA256SUMS.txt"
$distAbsolute = (Resolve-Path $DistRoot).Path
if (Test-Path $sumFile) {
    Remove-Item $sumFile -Force
}

Get-ChildItem -Path $DistRoot -Recurse -File | Where-Object { $_.Name -ne "SHA256SUMS.txt" } | ForEach-Object {
    try {
        $hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        $relative = $_.FullName.Substring($distAbsolute.Length).TrimStart('\', '/')
        [System.IO.File]::AppendAllText($sumFile, "$hash  $relative`n")
    } catch {
        Write-Warning "Skipped unreadable file: $($_.FullName)"
    }
}

Write-Host "Generated checksums at: $sumFile"
