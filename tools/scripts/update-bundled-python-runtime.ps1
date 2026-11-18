param(
    [string]$PythonVersion = "",
    [switch]$LatestStable,
    [string]$ManifestPath = "tools/manifest.json",
    [string]$RuntimeBuilderPath = "tools/scripts/build-runtime-venv.ps1"
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

function Get-StablePythonVersions {
    $indexUrl = "https://www.python.org/ftp/python/"
    $response = Invoke-WebRequest -Uri $indexUrl -UseBasicParsing
    $versions = [System.Collections.Generic.List[string]]::new()

    foreach ($match in [System.Text.RegularExpressions.Regex]::Matches($response.Content, 'href="(?<href>\d+\.\d+\.\d+)/"')) {
        $version = $match.Groups["href"].Value
        if (-not $versions.Contains($version)) {
            $versions.Add($version)
        }
    }

    return @($versions | Sort-Object { [version]$_ })
}

function Get-CurrentBundledPythonSeries {
    param([string]$ManifestFile)

    $manifest = Get-Content -Path $ManifestFile -Raw | ConvertFrom-Json
    $entry = $manifest.tools | Where-Object {
        $_.name -eq "python-runtime" -and $_.platform -eq "windows-amd64"
    } | Select-Object -First 1
    if (-not $entry) {
        throw "Manifest entry not found for python-runtime/windows-amd64 in $ManifestFile"
    }

    $versionText = [string]$entry.version
    $match = [System.Text.RegularExpressions.Regex]::Match(
        $versionText,
        "^(?<major>\d+)\.(?<minor>\d+)\."
    )
    if (-not $match.Success) {
        throw "Manifest python-runtime version is invalid: $versionText"
    }

    return "$($match.Groups['major'].Value).$($match.Groups['minor'].Value)"
}

function Resolve-TargetPythonVersion {
    param(
        [string]$RequestedVersion,
        [switch]$UseLatestStable,
        [string]$ManifestFile
    )

    if (-not [string]::IsNullOrWhiteSpace($RequestedVersion)) {
        return $RequestedVersion.Trim()
    }

    $versions = Get-StablePythonVersions
    if ($versions.Count -eq 0) {
        throw "No stable Python versions found in python.org FTP index."
    }

    if ($UseLatestStable) {
        return $versions[-1]
    }

    $series = Get-CurrentBundledPythonSeries -ManifestFile $ManifestFile
    $seriesVersions = @($versions | Where-Object { $_.StartsWith("$series.") })
    if ($seriesVersions.Count -eq 0) {
        throw "No stable Python releases found for current series $series in python.org FTP index."
    }
    return $seriesVersions[-1]
}

function Update-PythonRuntimeManifestEntry {
    param(
        [string]$ManifestFile,
        [string]$Version,
        [string]$RepoRoot
    )

    $manifest = Get-Content -Path $ManifestFile -Raw | ConvertFrom-Json
    $entry = $manifest.tools | Where-Object {
        $_.name -eq "python-runtime" -and $_.platform -eq "windows-amd64"
    } | Select-Object -First 1
    if (-not $entry) {
        throw "Manifest entry not found for python-runtime/windows-amd64 in $ManifestFile"
    }

    $runtimeExe = Join-Path $RepoRoot "vendor/bin/windows-amd64/python/python.exe"
    if (-not (Test-Path $runtimeExe)) {
        throw "Bundled runtime executable not found after update: $runtimeExe"
    }

    $entry.version = $Version
    $entry.sha256 = (Get-FileHash -Path $runtimeExe -Algorithm SHA256).Hash.ToLowerInvariant()

    $manifestJson = ($manifest | ConvertTo-Json -Depth 10) + "`n"
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($ManifestFile, $manifestJson, $utf8NoBom)
}

$repoRoot = Get-RepositoryRoot
$resolvedManifest = Resolve-RepoPath -RepoRoot $repoRoot -PathValue $ManifestPath
$resolvedBuilder = Resolve-RepoPath -RepoRoot $repoRoot -PathValue $RuntimeBuilderPath

if (-not (Test-Path $resolvedManifest)) {
    throw "Manifest not found: $resolvedManifest"
}
if (-not (Test-Path $resolvedBuilder)) {
    throw "Runtime builder script not found: $resolvedBuilder"
}

$targetVersion = Resolve-TargetPythonVersion -RequestedVersion $PythonVersion -UseLatestStable:$LatestStable -ManifestFile $resolvedManifest
Write-Host "Updating bundled Windows Python runtime to $targetVersion ..."

& powershell -ExecutionPolicy Bypass -File $resolvedBuilder -PythonVersion $targetVersion
if ($LASTEXITCODE -ne 0) {
    throw "Bundled Python runtime build failed with exit code $LASTEXITCODE"
}

Update-PythonRuntimeManifestEntry -ManifestFile $resolvedManifest -Version $targetVersion -RepoRoot $repoRoot
Write-Host "Updated bundled Windows Python runtime to $targetVersion and refreshed manifest metadata."
