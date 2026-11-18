param(
    [string]$OutputRoot = "dist/windows/lanlauncherng"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-RepositoryRoot {
    $scriptDir = Split-Path -Parent $PSCommandPath
    return (Resolve-Path (Join-Path $scriptDir "../..")).Path
}

function Resolve-OutputPath {
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

function Update-ToolManifestChecksums {
    param(
        [string]$ManifestPath,
        [string]$RepoRoot
    )

    if (-not (Test-Path $ManifestPath)) {
        throw "Tool manifest not found: $ManifestPath"
    }

    $manifest = Get-Content -Path $ManifestPath -Raw | ConvertFrom-Json
    if (-not ($manifest.PSObject.Properties.Name -contains "tools")) {
        throw "Invalid tool manifest: missing 'tools' array in $ManifestPath"
    }

    foreach ($tool in $manifest.tools) {
        $toolPath = Join-Path $RepoRoot $tool.path
        if (-not (Test-Path $toolPath)) {
            throw "Bundled tool not found for manifest refresh: $toolPath"
        }

        # Keep manifest checksums aligned with currently bundled binaries before packaging.
        $tool.sha256 = (Get-FileHash -Path $toolPath -Algorithm SHA256).Hash.ToLowerInvariant()
    }

    $manifestJson = ($manifest | ConvertTo-Json -Depth 10) + "`n"
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($ManifestPath, $manifestJson, $utf8NoBom)
    Write-Host "Refreshed bundled tool checksums: $ManifestPath"
}

function Assert-NoDeveloperMachineReferences {
    param(
        [string]$PackageRoot,
        [string[]]$Needles
    )

    $matches = @()
    $filteredNeedles = @($Needles | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)

    foreach ($file in Get-ChildItem -Path $PackageRoot -Recurse -File) {
        $bytes = [System.IO.File]::ReadAllBytes($file.FullName)
        foreach ($needle in $filteredNeedles) {
            $utf8 = [System.Text.Encoding]::UTF8.GetBytes($needle)
            $utf16 = [System.Text.Encoding]::Unicode.GetBytes($needle)
            if ($bytes.Length -ge $utf8.Length) {
                if ([System.Array]::IndexOf($bytes, $utf8[0]) -ge 0) {
                    $contentUtf8 = [System.Text.Encoding]::UTF8.GetString($bytes)
                    if ($contentUtf8.Contains($needle)) {
                        $matches += "$($file.FullName):$needle"
                        continue
                    }
                }
            }
            if ($bytes.Length -ge $utf16.Length) {
                $contentUtf16 = [System.Text.Encoding]::Unicode.GetString($bytes)
                if ($contentUtf16.Contains($needle)) {
                    $matches += "$($file.FullName):$needle"
                }
            }
        }
    }

    if ($matches.Count -gt 0) {
        throw "Developer machine path leakage detected in packaged bundle:`n$($matches -join "`n")"
    }
}

function Remove-PythonBuildArtifacts {
    param([string]$RootPath)

    Get-ChildItem -Path $RootPath -Recurse -Directory -Filter "__pycache__" | ForEach-Object {
        Remove-Item -Recurse -Force $_.FullName
    }
    Get-ChildItem -Path $RootPath -Recurse -File -Include "*.pyc", "*.pyo" | ForEach-Object {
        Remove-Item -Force $_.FullName
    }
}

$root = Get-RepositoryRoot
$out = Resolve-OutputPath -RepoRoot $root -PathValue $OutputRoot
$iconPath = Join-Path $root "src/frontend/assets/icons/lanlauncherng.ico"
$toolManifestPath = Join-Path $root "tools/manifest.json"
$runtimeRoot = Join-Path $root "vendor/bin/windows-amd64/python"
$runtimeVenvBuilder = Join-Path $root "tools/scripts/build-runtime-venv.ps1"

if (-not (Test-Path $iconPath)) {
    throw "App icon missing: $iconPath. Run ./.venv-dev-win/Scripts/python.exe tools/scripts/generate-app-icons.py"
}

if (-not (Test-Path (Join-Path $runtimeRoot "python.exe"))) {
    if (-not (Test-Path $runtimeVenvBuilder)) {
        throw "Windows embedded runtime not found at $runtimeRoot and builder script missing: $runtimeVenvBuilder"
    }
    $powerShellExe = Resolve-PowerShellBinary
    & $powerShellExe -ExecutionPolicy Bypass -File $runtimeVenvBuilder -RuntimePath $runtimeRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Windows embedded runtime build failed with exit code $LASTEXITCODE"
    }
}

$metadataRoots = @()
foreach ($candidate in @("library", "ng_provider")) {
    $candidatePath = Join-Path $root $candidate
    if (Test-Path $candidatePath -PathType Container) {
        $metadataRoots += $candidatePath
    }
}
if ($metadataRoots.Count -gt 0) {
    $metadataLinter = Join-Path $root "tools/scripts/lint_game_metadata.py"
    & (Join-Path $runtimeRoot "python.exe") $metadataLinter @metadataRoots
    if ($LASTEXITCODE -ne 0) {
        throw "Game metadata action lint failed with exit code $LASTEXITCODE"
    }
}

Update-ToolManifestChecksums -ManifestPath $toolManifestPath -RepoRoot $root

if (Test-Path $out) {
    Remove-Item -Recurse -Force $out
}

$dirs = @(
    $out,
    (Join-Path $out "app"),
    (Join-Path $out "config"),
    (Join-Path $out "config/install"),
    (Join-Path $out "config/resilio"),
    (Join-Path $out "data"),
    (Join-Path $out "data/library"),
    (Join-Path $out "data/legacy"),
    (Join-Path $out "data/logs"),
    (Join-Path $out "data/sync"),
    (Join-Path $out "data/ouisync"),
    (Join-Path $out "vendor"),
    (Join-Path $out "vendor/bin"),
    (Join-Path $out "vendor/bin/windows-amd64"),
    (Join-Path $out "vendor/python"),
    (Join-Path $out "vendor/licenses"),
    (Join-Path $out "vendor/licenses/ouisync"),
    (Join-Path $out "vendor/licenses/msgpack"),
    (Join-Path $out "vendor/licenses/python"),
    (Join-Path $out "vendor/licenses/resilio"),
    (Join-Path $out "vendor/licenses/unrar"),
    (Join-Path $out "site"),
    (Join-Path $out "docs"),
    (Join-Path $out "scripts"),
    (Join-Path $out "scripts/wrappers"),
    (Join-Path $out "scripts/checks")
)

foreach ($d in $dirs) {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
}

Copy-Item -Recurse -Force (Join-Path $root "src") (Join-Path $out "app/src")
Remove-PythonBuildArtifacts -RootPath (Join-Path $out "app/src")
Copy-Item -Recurse -Force (Join-Path $root "tools") (Join-Path $out "app/tools")
Remove-PythonBuildArtifacts -RootPath (Join-Path $out "app/tools")
if (Test-Path (Join-Path $root "VERSION")) {
    Copy-Item -Force (Join-Path $root "VERSION") (Join-Path $out "VERSION")
}
Copy-Item -Recurse -Force (Join-Path $root "vendor/bin/windows-amd64/*") (Join-Path $out "vendor/bin/windows-amd64")
if (Test-Path (Join-Path $root "vendor/python")) {
    Copy-Item -Recurse -Force (Join-Path $root "vendor/python/*") (Join-Path $out "vendor/python")
    Remove-PythonBuildArtifacts -RootPath (Join-Path $out "vendor/python")
}
Copy-Item -Force (Join-Path $root "vendor/licenses/ouisync/*") (Join-Path $out "vendor/licenses/ouisync")
Copy-Item -Force (Join-Path $root "vendor/licenses/msgpack/LICENSE.txt") (Join-Path $out "vendor/licenses/msgpack/LICENSE.txt")
if (Test-Path (Join-Path $root "vendor/licenses/python/LICENSE.txt")) {
    Copy-Item -Force (Join-Path $root "vendor/licenses/python/LICENSE.txt") (Join-Path $out "vendor/licenses/python/LICENSE.txt")
}
if (Test-Path (Join-Path $root "vendor/licenses/unrar/LICENSE.txt")) {
    Copy-Item -Force (Join-Path $root "vendor/licenses/unrar/LICENSE.txt") (Join-Path $out "vendor/licenses/unrar/LICENSE.txt")
}
Copy-Item -Recurse -Force (Join-Path $root "docs/*") (Join-Path $out "docs")
if (Test-Path (Join-Path $root "site")) {
    Copy-Item -Recurse -Force (Join-Path $root "site/*") (Join-Path $out "site")
} else {
    Write-Warning "Compiled docs folder 'site\\' not found; local docs link will be unavailable until site is generated."
}
if (Test-Path (Join-Path $root "scripts")) {
    Copy-Item -Recurse -Force (Join-Path $root "scripts/*") (Join-Path $out "scripts")
}
if (Test-Path (Join-Path $root "config/install/checks.json")) {
    Copy-Item -Force (Join-Path $root "config/install/checks.json") (Join-Path $out "config/install/checks.json")
}
if (Test-Path (Join-Path $root "config/resilio/config.yml")) {
    Copy-Item -Force (Join-Path $root "config/resilio/config.yml") (Join-Path $out "config/resilio/config.yml")
}
if (Test-Path (Join-Path $root "config/resilio/config.json")) {
    Copy-Item -Force (Join-Path $root "config/resilio/config.json") (Join-Path $out "config/resilio/config.json")
}
if (Test-Path (Join-Path $root "config/bootstrap.json")) {
    Copy-Item -Force (Join-Path $root "config/bootstrap.json") (Join-Path $out "config/bootstrap.json")
}
if (Test-Path (Join-Path $root "config/feature-flags.json")) {
    Copy-Item -Force (Join-Path $root "config/feature-flags.json") (Join-Path $out "config/feature-flags.json")
}
if (Test-Path (Join-Path $root "old/game.db")) {
    Copy-Item -Force (Join-Path $root "old/game.db") (Join-Path $out "data/legacy/game.db")
}

$configPath = Join-Path $out "config/core.json"
@'
{
  "bind_host": "127.0.0.1",
  "bind_port": 18080,
  "db_path": "data/lanlauncher.db",
  "legacy_db_path": "data/legacy/game.db",
  "library_path": "data/library",
  "log_path": "data/logs/log.txt",
  "log_level": "WARNING",
  "default_locale": "en",
  "sync_provider": "ouisync",
  "sync_binary_path": "vendor/bin/windows-amd64/btsync.exe",
  "sync_config_path": "config/resilio/config.json",
  "sync_pid_path": "data/sync/rslsync.pid",
  "sync_log_path": "data/logs/resilio-sync.log",
  "sync_license_key_path": "vendor/licenses/resilio/llng.btskey",
  "sync_api_url": "http://127.0.0.1:13338/api",

  "sync_api_key": "VGWWKFEB2BVHKUNMUPMZHTZFNEVSPWT5CO3UKNKOMXL54FOYDF7VQ2FTUK2M7HXQRMRZ4H5XPABI3NKR7EMCMCVEJDGG54RDO56AGASC2WTU366TPMDTTH4HUS4XWL2LIA",
  "sync_request_timeout_seconds": 2,
  "sync_retry_count": 3,
  "sync_startup_retry_seconds": 8,
  "ouisync_binary_path": "vendor/bin/windows-amd64/ouisync.exe",
  "ouisync_config_dir": "data/ouisync",
  "ouisync_log_path": "data/logs/ouisync.log",
  "ouisync_startup_timeout_seconds": 15,
  "tool_manifest_path": "app/tools/manifest.json",
  "repo_root": ".",
  "install_scripts_root": "scripts/wrappers",
  "install_checks_path": "config/install/checks.json",
  "linux_cmd_wrapper_path": "scripts/wrappers/linux/run-cmd-wrapper.sh",
  "settings_path": "data/settings.json",
  "default_extra_sync_items_path": "config/bootstrap.json",
  "feature_flags_path": "config/feature-flags.json",
  "update_manifest_path": "ng_provider/update/update-manifest.json"
}
'@ | Set-Content $configPath

@'
@echo off
setlocal
cd /d %~dp0
echo.
echo   +----------------------------------------------------------------------------------+
echo   ^|     __    ___    _   ____                           __              _   ________ ^|
echo   ^|    / /   /   ^|  / ^| / / /   ____ ___  ______  _____/ /_  ___  _____/ ^| / / ____/ ^|
echo   ^|   / /   / /^| ^| /  ^|/ / /   / __ `/ / / / __ \/ ___/ __ \/ _ \/ ___/  ^|/ / / __   ^|
echo   ^|  / /___/ ___ ^|/ /^|  / /___/ /_/ / /_/ / / / / /__/ / / /  __/ /  / /^|  / /_/ /   ^|
echo   ^| /_____/_/  ^|_/_/ ^|_/_____/\__,_/\__,_/_/ /_/\___/_/ /_/\___/_/  /_/ ^|_/\____/    ^|
echo   ^|                                                                                  ^|
echo   +----------------------------------------------------------------------------------+
echo.
echo  LANLauncherNG is running in this window.
echo  Do NOT close this window while the launcher is active.
echo.
if not exist ".\vendor\bin\windows-amd64\python\python.exe" (
  echo Missing bundled Python runtime: vendor\bin\windows-amd64\python\python.exe
  exit /b 1
)
set "PY_EXE=.\vendor\bin\windows-amd64\python\python.exe"
if not exist "%PY_EXE%" (
  echo Missing Python executable: vendor\bin\windows-amd64\python\python.exe
  exit /b 1
)
set "LLNG_LOG_LEVEL=INFO"
"%PY_EXE%" -m src.core.main --config config\core.json
'@ | Set-Content (Join-Path $out "run.bat")

$leakNeedles = @(
    $root,
    $env:HOME,
    $env:USERPROFILE
)
Assert-NoDeveloperMachineReferences -PackageRoot $out -Needles $leakNeedles

Write-Host "Windows package created at: $out"
