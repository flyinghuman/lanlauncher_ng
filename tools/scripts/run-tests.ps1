param(
    [switch]$VerboseOutput
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$python = ".\\.venv-dev-win\\Scripts\\python.exe"
if (-not (Test-Path $python)) {
    throw "Python virtual environment not found at .venv-dev-win."
}

# The Windows test interpreter is sometimes run through Wine from Linux. Mark
# that environment so tests requiring Windows PowerShell or the Dokan driver
# can be skipped while the remaining Windows tests still run.
if ($PSVersionTable.PSVersion.Major -ge 6 -and $IsLinux -and (Get-Command wine -ErrorAction SilentlyContinue)) {
    $env:LLNG_TEST_WINE = "1"
}

$verbosity = if ($VerboseOutput) { "-v" } else { "" }

# Use explicit unittest discovery so all project tests run consistently.
& $python -m unittest discover -s tests -p "test_*.py" -t . $verbosity
exit $LASTEXITCODE
