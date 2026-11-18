param(
    [string]$PackageRoot = "dist/windows/lanlauncherng",
    [string]$InstallerScript = "packaging/windows/inno/lanlauncherng.iss",
    [string]$UpdateOutputDir = "dist/windows/update",
    [string]$ManifestName = "update-manifest.json",
    [string]$InstallTargetPath = ".",
    [string]$PreservePaths = "data",
    [string]$HealthCheckType = "none",
    [string]$HealthCheckPath = "",
    [string]$KeyId = "llng-root-2026",
    [string]$PrivateKeyPath = "secrets/llng-update-private.pem",
    [string]$PublicKeyPath = "secrets/llng-update-public.pem",
    [string]$OpensslBin = "openssl",
    [switch]$UnsignedUpdate,
    [switch]$SkipPackageBuild,
    [switch]$SkipPublicKeyRegistration
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-RepositoryRoot {
    $scriptDir = Split-Path -Parent $PSCommandPath
    return (Resolve-Path (Join-Path $scriptDir "../..")).Path
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

function Resolve-PythonCommand {
    param([string]$RepoRoot)
    $vendorPython = Join-Path $RepoRoot "vendor/bin/windows-amd64/python/python.exe"
    if (Test-Path $vendorPython) {
        return $vendorPython
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    throw "Python interpreter not found (vendor/bin/windows-amd64/python/python.exe or python in PATH)."
}

$repoRoot = Get-RepositoryRoot
$resolvedPackageRoot = Resolve-RepoPath -RepoRoot $repoRoot -PathValue $PackageRoot
$resolvedInstallerScript = Resolve-RepoPath -RepoRoot $repoRoot -PathValue $InstallerScript
$resolvedUpdateOutputDir = Resolve-RepoPath -RepoRoot $repoRoot -PathValue $UpdateOutputDir
$packageBuilder = Join-Path $repoRoot "tools/scripts/package-windows.ps1"
$installerBuilder = Join-Path $repoRoot "tools/scripts/build-installer-windows.ps1"
$updateBuilder = Join-Path $repoRoot "tools/scripts/build_update_package.py"
$pythonExe = Resolve-PythonCommand -RepoRoot $repoRoot
$powerShellExe = Resolve-PowerShellBinary

if (-not (Test-Path $installerBuilder)) {
    throw "Installer build script not found: $installerBuilder"
}
if (-not (Test-Path $packageBuilder)) {
    throw "Package build script not found: $packageBuilder"
}
if (-not (Test-Path $updateBuilder)) {
    throw "Update package script not found: $updateBuilder"
}
if (-not $UnsignedUpdate -and [string]::IsNullOrWhiteSpace($PrivateKeyPath)) {
    throw "PrivateKeyPath is required unless -UnsignedUpdate is used."
}

if (-not $SkipPackageBuild) {
    & $powerShellExe -ExecutionPolicy Bypass -File $packageBuilder -OutputRoot $resolvedPackageRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Package build failed with exit code $LASTEXITCODE"
    }
}

$installerArgs = @(
    "-ExecutionPolicy", "Bypass",
    "-File", $installerBuilder,
    "-PackageRoot", $resolvedPackageRoot,
    "-InnoScript", $resolvedInstallerScript,
    "-SkipPackageBuild"
)

& $powerShellExe @installerArgs
if ($LASTEXITCODE -ne 0) {
    throw "Installer build failed with exit code $LASTEXITCODE"
}

$updateArgs = @(
    $updateBuilder,
    "--package-root", $resolvedPackageRoot,
    "--output-dir", $resolvedUpdateOutputDir,
    "--manifest-name", $ManifestName,
    "--install-target-path", $InstallTargetPath,
    "--preserve-paths", $PreservePaths,
    "--health-check-type", $HealthCheckType,
    "--key-id", $KeyId,
    "--openssl-bin", $OpensslBin,
    "--package-script", $packageBuilder,
    "--overwrite"
)
if (-not [string]::IsNullOrWhiteSpace($HealthCheckPath)) {
    $updateArgs += @("--health-check-path", $HealthCheckPath)
} elseif ($HealthCheckType -eq "file_exists") {
    throw "HealthCheckPath is required when HealthCheckType is file_exists."
}
if ($SkipPackageBuild) {
    $updateArgs += "--skip-package-build"
}
if (-not $SkipPublicKeyRegistration) {
    $resolvedPublicKey = Resolve-RepoPath -RepoRoot $repoRoot -PathValue $PublicKeyPath
    $updateArgs += @(
        "--register-public-key",
        "--public-key", $resolvedPublicKey
    )
}
if ($UnsignedUpdate) {
    $updateArgs += "--unsigned"
} else {
    $resolvedPrivateKey = Resolve-RepoPath -RepoRoot $repoRoot -PathValue $PrivateKeyPath
    $updateArgs += @("--private-key", $resolvedPrivateKey)
}

& $pythonExe @updateArgs
if ($LASTEXITCODE -ne 0) {
    throw "Update package build failed with exit code $LASTEXITCODE"
}

Write-Host "Installer + update package build complete."
Write-Host "Installer output: dist/windows/installer"
Write-Host "Update output: $resolvedUpdateOutputDir"
