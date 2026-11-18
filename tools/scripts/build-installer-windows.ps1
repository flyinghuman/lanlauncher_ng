param(
    [string]$PackageRoot = "dist/windows/lanlauncher",
    [string]$InnoScript = "packaging/windows/inno/lanlauncherng.iss",
    [switch]$SkipPackageBuild
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-RepositoryRoot {
    $scriptDir = Split-Path -Parent $PSCommandPath
    return (Resolve-Path (Join-Path $scriptDir "../..")).Path
}

function Update-ToolManifestChecksums {
    param(
        [string]$ManifestPath,
        [string]$BaseRoot,
        [string]$TargetPlatform = ""
    )

    if (-not (Test-Path $ManifestPath)) {
        throw "Tool manifest not found: $ManifestPath"
    }

    $manifest = Get-Content -Path $ManifestPath -Raw | ConvertFrom-Json
    if (-not ($manifest.PSObject.Properties.Name -contains "tools")) {
        throw "Invalid tool manifest: missing 'tools' array in $ManifestPath"
    }

    foreach ($tool in $manifest.tools) {
        $toolPlatform = [string]$tool.platform
        if (-not [string]::IsNullOrWhiteSpace($TargetPlatform) -and -not [string]::IsNullOrWhiteSpace($toolPlatform) -and $toolPlatform -ne "any" -and $toolPlatform -ne $TargetPlatform) {
            continue
        }

        $toolPath = Join-Path $BaseRoot $tool.path
        if (-not (Test-Path $toolPath)) {
            throw "Bundled tool not found for manifest refresh: $toolPath"
        }

        # Refresh hashes against the current payload root (repo or prebuilt package root).
        $tool.sha256 = (Get-FileHash -Path $toolPath -Algorithm SHA256).Hash.ToLowerInvariant()
    }

    $manifestJson = ($manifest | ConvertTo-Json -Depth 10) + "`n"
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($ManifestPath, $manifestJson, $utf8NoBom)
    Write-Host "Refreshed bundled tool checksums: $ManifestPath"
}

function Resolve-RepoPath {
    param(
        [string]$RepoRoot,
        [string]$PathValue
    )

    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return $PathValue
    }

    return (Join-Path $RepoRoot $PathValue)
}

function Resolve-PowerShellBinary {
    foreach ($candidate in @("pwsh", "powershell")) {
        $resolved = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($resolved) {
            return $resolved.Source
        }
    }
    throw "PowerShell executable not found (pwsh/powershell)."
}

function Convert-ToWinePath {
    param(
        [string]$PathValue
    )

    $winepath = Get-Command winepath -ErrorAction SilentlyContinue
    if ($winepath) {
        $winepathExe = $winepath.Source
        if ([string]::IsNullOrWhiteSpace($winepathExe)) {
            $winepathExe = $winepath.Path
        }
        if (-not [string]::IsNullOrWhiteSpace($winepathExe)) {
            try {
                $converted = (& $winepathExe -w $PathValue).Trim()
                if (-not [string]::IsNullOrWhiteSpace($converted)) {
                    return $converted
                }
            } catch {
                # Fall back to a deterministic Z: mapping when Wine's helper is unavailable.
            }
        }
    }

    # Fallback mapping for standard Wine Z: drive to Linux filesystem root.
    $normalized = $PathValue -replace "\\", "/"
    return "Z:$normalized" -replace "/", "\"
}

$repoRoot = Get-RepositoryRoot
$resolvedPackageRoot = Resolve-RepoPath -RepoRoot $repoRoot -PathValue $PackageRoot
$resolvedInnoScript = Resolve-RepoPath -RepoRoot $repoRoot -PathValue $InnoScript
$resolvedPackageScript = Join-Path $repoRoot "tools/scripts/package-windows.ps1"
$runtimeBuilder = Join-Path $repoRoot "tools/scripts/build-runtime-venv.ps1"
$runtimePython = Join-Path $repoRoot "vendor/bin/windows-amd64/python/python.exe"
$powerShellExe = Resolve-PowerShellBinary
$homeDir = if ([string]::IsNullOrWhiteSpace($env:HOME)) {
    [Environment]::GetFolderPath("UserProfile")
} else {
    $env:HOME
}

if ($SkipPackageBuild) {
    $packagedManifest = Join-Path $resolvedPackageRoot "app/tools/manifest.json"
    if (-not (Test-Path $packagedManifest)) {
        throw "Packaged tool manifest not found: $packagedManifest"
    }

    Update-ToolManifestChecksums -ManifestPath $packagedManifest -BaseRoot $resolvedPackageRoot -TargetPlatform "windows-amd64"
} else {
    if (-not (Test-Path $runtimePython)) {
        if (-not (Test-Path $runtimeBuilder)) {
            throw "Windows embedded runtime builder not found: $runtimeBuilder"
        }
        & $powerShellExe -ExecutionPolicy Bypass -File $runtimeBuilder
        if ($LASTEXITCODE -ne 0) {
            throw "Windows embedded runtime build failed with exit code $LASTEXITCODE"
        }
    }
    Update-ToolManifestChecksums -ManifestPath (Join-Path $repoRoot "tools/manifest.json") -BaseRoot $repoRoot
}

if (-not $SkipPackageBuild) {
    & $powerShellExe -ExecutionPolicy Bypass -File $resolvedPackageScript -OutputRoot $resolvedPackageRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Package build failed with exit code $LASTEXITCODE"
    }
}

if (-not (Test-Path $resolvedPackageRoot)) {
    throw "Windows package root not found: $resolvedPackageRoot"
}

if (-not (Test-Path $resolvedInnoScript)) {
    throw "Inno script not found: $resolvedInnoScript"
}

$isccCandidates = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
    "P:\Programme\Inno Setup 6\ISCC.exe",
    "${env:SystemDrive}\Programme\Inno Setup 6\ISCC.exe",
    (Join-Path $homeDir ".wine/drive_c/Program Files (x86)/Inno Setup 6/ISCC.exe")
)

$iscc = $null
foreach ($candidate in $isccCandidates) {
    if (Test-Path $candidate) {
        $iscc = $candidate
        break
    }
}

if (-not $iscc) {
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) {
        $iscc = $cmd.Source
    }
}

if (-not $iscc) {
    throw "Inno Setup compiler (ISCC.exe) not found. Install Inno Setup 6 and rerun."
}

$versionFile = Join-Path $repoRoot "VERSION"
if (-not (Test-Path $versionFile)) {
    throw "VERSION file not found: $versionFile"
}
$appVersion = (Get-Content $versionFile -Raw).Trim()
if ([string]::IsNullOrWhiteSpace($appVersion)) {
    throw "VERSION file is empty: $versionFile"
}

$normalizedIsccPath = $iscc -replace "\\", "/"
# Detect Wine-hosted ISCC by its resolved path so the script also works in Windows PowerShell,
# where automatic platform variables like $IsLinux are not defined under strict mode.
$isWineIscc = $normalizedIsccPath -like "*/.wine/*"
if ($isWineIscc) {
    $wineCmd = Get-Command wine -ErrorAction SilentlyContinue
    if (-not $wineCmd) {
        throw "Wine is required to run ISCC.exe from .wine on Linux. Install wine and rerun."
    }
    $winePackageRoot = Convert-ToWinePath -PathValue $resolvedPackageRoot
    $wineInnoScript = Convert-ToWinePath -PathValue $resolvedInnoScript
    $isccArgs = @(
        "/DMyAppVersion=$appVersion",
        "/DPackageRoot=$winePackageRoot",
        $wineInnoScript
    )
    & $wineCmd.Source $iscc @isccArgs
} else {
    $isccArgs = @(
        "/DMyAppVersion=$appVersion",
        "/DPackageRoot=$resolvedPackageRoot",
        $resolvedInnoScript
    )
    & $iscc @isccArgs
}
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup compilation failed with exit code $LASTEXITCODE"
}

$installerOutputDir = Join-Path $repoRoot "dist/windows/installer"
New-Item -ItemType Directory -Force -Path $installerOutputDir | Out-Null
Remove-Item -LiteralPath (Join-Path $installerOutputDir "bootstrap.json") -Force -ErrorAction SilentlyContinue
foreach ($readmeName in @("README.md", "README.txt")) {
    Copy-Item -Force (Join-Path $repoRoot "packaging/windows/$readmeName") (Join-Path $installerOutputDir $readmeName)
}
$optionalBootstrap = Join-Path $repoRoot "ng_provider/bootstrap.json"
if (Test-Path $optionalBootstrap) {
    Copy-Item -Force $optionalBootstrap (Join-Path $installerOutputDir "bootstrap.json")
}

Write-Host "Windows installer created under dist/windows/installer"
