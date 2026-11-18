param(
    [string]$RuntimePath = "vendor/bin/windows-amd64/python",
    [string]$PythonVersion = "3.14.0",
    [string]$CacheDir = ".cache/python-runtime-win",
    [switch]$ForceDownload
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

function Get-PythonRuntimeTag {
    param([string]$Version)

    $match = [System.Text.RegularExpressions.Regex]::Match(
        $Version,
        "^(?<major>\d+)\.(?<minor>\d+)\."
    )
    if (-not $match.Success) {
        throw "PythonVersion must use <major>.<minor>.<patch>: $Version"
    }

    return "$($match.Groups['major'].Value)$($match.Groups['minor'].Value)"
}

function Write-PthFile {
    param(
        [string]$RuntimeRoot,
        [string]$RuntimeTag
    )

    $pthPath = Join-Path $RuntimeRoot "python$RuntimeTag._pth"
    if (-not (Test-Path $pthPath)) {
        throw "Embedded runtime path file not found: $pthPath"
    }

    # Keep imports restricted to the bundled stdlib zip, the runtime root, the
    # vendored site-packages directory, and the packaged app tree.
    $pthContents = @(
        "python$RuntimeTag.zip",
        ".",
        "Lib\site-packages",
        "..\..\..\..\app",
        "import site"
    )
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($pthPath, $pthContents, $utf8NoBom)
}

$repoRoot = Get-RepositoryRoot
$runtimeRoot = Resolve-RepoPath -RepoRoot $repoRoot -PathValue $RuntimePath
$cacheRoot = Resolve-RepoPath -RepoRoot $repoRoot -PathValue $CacheDir
$licenseRoot = Join-Path $repoRoot "vendor/licenses/python"
$pythonTag = Get-PythonRuntimeTag -Version $PythonVersion
$archiveName = "python-$PythonVersion-embed-amd64.zip"
$archivePath = Join-Path $cacheRoot $archiveName
$downloadUrl = "https://www.python.org/ftp/python/$PythonVersion/$archiveName"

New-Item -ItemType Directory -Force -Path $cacheRoot | Out-Null

if ($ForceDownload -or -not (Test-Path $archivePath)) {
    Write-Host "Downloading embedded Python runtime from $downloadUrl ..."
    Invoke-WebRequest -Uri $downloadUrl -OutFile $archivePath
}

if (Test-Path $runtimeRoot) {
    Remove-Item -Recurse -Force $runtimeRoot
}
New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null

$extractRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("llng-python-embed-" + [System.Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $extractRoot | Out-Null

try {
    Expand-Archive -Path $archivePath -DestinationPath $extractRoot -Force
    Copy-Item -Recurse -Force (Join-Path $extractRoot "*") $runtimeRoot

    $pythonExe = Join-Path $runtimeRoot "python.exe"
    if (-not (Test-Path $pythonExe)) {
        throw "Embedded runtime extraction failed: missing $pythonExe"
    }

    New-Item -ItemType Directory -Force -Path (Join-Path $runtimeRoot "Lib/site-packages") | Out-Null
    Write-PthFile -RuntimeRoot $runtimeRoot -RuntimeTag $pythonTag

    $licenseSource = Join-Path $runtimeRoot "LICENSE.txt"
    if (-not (Test-Path $licenseSource)) {
        throw "Embedded runtime does not contain LICENSE.txt: $archivePath"
    }

    New-Item -ItemType Directory -Force -Path $licenseRoot | Out-Null
    Copy-Item -Force $licenseSource (Join-Path $licenseRoot "LICENSE.txt")
} finally {
    if (Test-Path $extractRoot) {
        Remove-Item -Recurse -Force $extractRoot
    }
}

Write-Host "Windows embedded runtime prepared at: $runtimeRoot"
