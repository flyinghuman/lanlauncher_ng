param(
    [string]$EnDir = "src/frontend/app/locales/en",
    [string]$DeDir = "src/frontend/app/locales/de"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-JsonLeafKeys {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Node,
        [string]$Prefix = ""
    )

    $keys = @()

    # Flatten nested locale objects to dot-separated leaf keys for stable parity checks.
    if ($Node -is [System.Collections.IDictionary]) {
        foreach ($k in $Node.Keys) {
            $next = if ([string]::IsNullOrEmpty($Prefix)) { "$k" } else { "$Prefix.$k" }
            $keys += Get-JsonLeafKeys -Node $Node[$k] -Prefix $next
        }
        return $keys
    }

    if ($Node -is [pscustomobject]) {
        foreach ($prop in $Node.PSObject.Properties) {
            $k = $prop.Name
            $next = if ([string]::IsNullOrEmpty($Prefix)) { "$k" } else { "$Prefix.$k" }
            $keys += Get-JsonLeafKeys -Node $prop.Value -Prefix $next
        }
        return $keys
    }

    if ($Node -is [System.Collections.IEnumerable] -and -not ($Node -is [string])) {
        $i = 0
        foreach ($item in $Node) {
            $next = if ([string]::IsNullOrEmpty($Prefix)) { "[$i]" } else { "$Prefix[$i]" }
            $keys += Get-JsonLeafKeys -Node $item -Prefix $next
            $i++
        }
        return $keys
    }

    return @($Prefix)
}

function Load-LocaleKeySet {
    param([string]$Dir)

    if (-not (Test-Path $Dir)) {
        throw "Locale directory not found: $Dir"
    }

    $set = New-Object 'System.Collections.Generic.HashSet[string]'

    Get-ChildItem -Path $Dir -File -Filter *.json | ForEach-Object {
        $jsonText = Get-Content $_.FullName -Raw
        $obj = $jsonText | ConvertFrom-Json
        $filePrefix = [System.IO.Path]::GetFileNameWithoutExtension($_.Name)

        foreach ($k in (Get-JsonLeafKeys -Node $obj)) {
            [void]$set.Add("$filePrefix.$k")
        }
    }

    return $set
}

$enKeys = Load-LocaleKeySet -Dir $EnDir
$deKeys = Load-LocaleKeySet -Dir $DeDir

$missingInDe = @($enKeys.Where({ -not $deKeys.Contains($_) }) | Sort-Object)
$missingInEn = @($deKeys.Where({ -not $enKeys.Contains($_) }) | Sort-Object)

if ($missingInDe.Count -eq 0 -and $missingInEn.Count -eq 0) {
    Write-Host "OK: locale key parity check passed (EN == DE)."
    exit 0
}

Write-Error "Locale key parity check failed."
if ($missingInDe.Count -gt 0) {
    Write-Host "Missing in DE:"
    $missingInDe | ForEach-Object { Write-Host "  - $_" }
}
if ($missingInEn.Count -gt 0) {
    Write-Host "Missing in EN:"
    $missingInEn | ForEach-Object { Write-Host "  - $_" }
}
exit 1
