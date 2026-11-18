param(
    [string]$VenvPath = ".venv-dev-win",
    [string]$PythonBin = "",
    [string]$RequirementsPath = "requirements-dev-win.txt"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-PythonCommand {
    param([string]$Requested)

    function Test-UsablePythonPath {
        param([string]$Candidate)
        if ([string]::IsNullOrWhiteSpace($Candidate)) {
            return $false
        }
        if (-not (Test-Path $Candidate)) {
            return $false
        }
        if ($Candidate.ToLowerInvariant().Contains("\windowsapps\")) {
            return $false
        }
        return $true
    }

    if (-not [string]::IsNullOrWhiteSpace($Requested)) {
        if (-not (Test-UsablePythonPath $Requested)) {
            throw "Requested Python interpreter not found: $Requested"
        }
        return (Resolve-Path $Requested).Path
    }

    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and (Test-UsablePythonPath $cmd.Source)) {
        return $cmd.Source
    }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return $py.Source
    }

    throw "No Python interpreter found (python/py)."
}

$repoRoot = (Get-Location).Path
$pythonExe = Resolve-PythonCommand -Requested $PythonBin
$target = if ([System.IO.Path]::IsPathRooted($VenvPath)) { $VenvPath } else { Join-Path $repoRoot $VenvPath }
$requirementsFile = if ([System.IO.Path]::IsPathRooted($RequirementsPath)) { $RequirementsPath } else { Join-Path $repoRoot $RequirementsPath }

if (-not (Test-Path $requirementsFile)) {
    throw "Requirements file not found: $requirementsFile"
}

if (Test-Path $target) {
    Remove-Item -Recurse -Force $target
}

if ($pythonExe.ToLowerInvariant().EndsWith("\py.exe")) {
    & $pythonExe -3 -m venv $target
} else {
    & $pythonExe -m venv $target
}
if ($LASTEXITCODE -ne 0) {
    throw "Dev venv creation failed with exit code $LASTEXITCODE"
}

$venvPython = Join-Path $target "Scripts/python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Dev venv python not found: $venvPython"
}

# Keep the dev environment separate from runtime packaging so Windows tooling
# can carry docs/test helpers without bloating the shipped runtime env.
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "pip upgrade failed with exit code $LASTEXITCODE"
}
& $venvPython -m pip install -r $requirementsFile
if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed with exit code $LASTEXITCODE"
}

Write-Host "Windows dev venv created at: $target"
