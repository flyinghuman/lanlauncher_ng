param(
    [Parameter(Mandatory = $true)]
    [string]$ManifestPath,
    [Parameter(Mandatory = $true)]
    [string]$CurrentVersion,
    [Parameter(Mandatory = $true)]
    [string]$TargetVersion,
    [Parameter(Mandatory = $true)]
    [string]$SessionId,
    [Parameter(Mandatory = $true)]
    [string]$PayloadPath,
    [Parameter(Mandatory = $true)]
    [string]$PayloadSha256,
    [Parameter(Mandatory = $true)]
    [string]$InstallMode,
    [Parameter(Mandatory = $false)]
    [string]$InstallTargetPath = "",
    [Parameter(Mandatory = $false)]
    [string]$PreservePathsCsv = "data",
    [Parameter(Mandatory = $false)]
    [string]$HealthCheckType = "none",
    [Parameter(Mandatory = $false)]
    [string]$HealthCheckPath = "",
    [Parameter(Mandatory = $true)]
    [string]$RepoRoot,
    [Parameter(Mandatory = $false)]
    [switch]$ElevatedChild,
    [Parameter(Mandatory = $false)]
    [int]$ParentProcessId = 0
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptPath = $PSCommandPath
$resolvedTargetPath = ""
$defaultJournalDir = Join-Path $RepoRoot "data/update"
$runtimeMetadataOutsideTarget = $false
$journalDir = ""
$stagingDir = ""
$backupRoot = ""
$backupDir = ""
$lockPath = ""
$journalPath = ""
$journalStepsPath = ""
$activeLockPath = ""
$finalExitCode = -1
$finalStatusMessage = ""

function Set-RuntimePaths([string]$baseJournalDir) {
    $script:journalDir = $baseJournalDir
    $script:stagingDir = Join-Path $script:journalDir "staging\$SessionId"
    $script:backupRoot = Join-Path $script:journalDir "backup"
    $script:backupDir = Join-Path $script:backupRoot $SessionId
    $script:lockPath = Join-Path $script:journalDir "updater.lock"
    $script:journalPath = Join-Path $script:journalDir "last-run.json"
    $script:journalStepsPath = Join-Path $script:journalDir "session-$SessionId.json"
}

function Test-PathWithin([string]$childPath, [string]$parentPath) {
    if (-not $childPath -or -not $parentPath) {
        return $false
    }
    $childFull = [System.IO.Path]::GetFullPath($childPath).TrimEnd("\")
    $parentFull = [System.IO.Path]::GetFullPath($parentPath).TrimEnd("\")
    if (-not $childFull -or -not $parentFull) {
        return $false
    }
    if ($childFull.Equals($parentFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    return $childFull.StartsWith(
        $parentFull + "\",
        [System.StringComparison]::OrdinalIgnoreCase
    )
}

function Promote-RuntimeMetadataToTarget([string]$targetPath) {
    if (-not $script:runtimeMetadataOutsideTarget) {
        return
    }
    if (-not $targetPath -or -not (Test-Path -LiteralPath $targetPath -PathType Container)) {
        return
    }

    $finalJournalDir = Join-Path $targetPath "data/update"
    New-Item -ItemType Directory -Path $finalJournalDir -Force | Out-Null
    $finalBackupDir = Join-Path (Join-Path $finalJournalDir "backup") $SessionId
    if (Test-Path -LiteralPath $script:backupDir) {
        if (Test-Path -LiteralPath $finalBackupDir) {
            Remove-Item -LiteralPath $finalBackupDir -Recurse -Force
        }
        Copy-Item -LiteralPath $script:backupDir -Destination $finalBackupDir -Recurse -Force
    }
    Set-RuntimePaths $finalJournalDir
    $script:runtimeMetadataOutsideTarget = $false
}

function Remove-StaleUpdaterStateFromBackup([string]$backupCurrentPath) {
    if (-not $backupCurrentPath -or -not (Test-Path -LiteralPath $backupCurrentPath -PathType Container)) {
        return
    }
    # Keep exactly one rollback snapshot. Older updater runtime state inside the
    # moved install root would otherwise recurse into the next preserved backup.
    $nestedUpdateDir = Join-Path $backupCurrentPath "data\update"
    if (Test-Path -LiteralPath $nestedUpdateDir) {
        Remove-Item -LiteralPath $nestedUpdateDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Copy-PreservedPath([string]$fromPath, [string]$toPath, [string]$relativePath) {
    if (-not (Test-Path -LiteralPath $fromPath)) {
        return
    }
    $toParent = Split-Path -Path $toPath -Parent
    if ($toParent) {
        New-Item -ItemType Directory -Path $toParent -Force | Out-Null
    }
    if (Test-Path -LiteralPath $toPath) {
        Remove-Item -LiteralPath $toPath -Recurse -Force
    }
    Copy-Item -LiteralPath $fromPath -Destination $toPath -Recurse -Force
    if ($relativePath -ieq "data") {
        $copiedUpdateDir = Join-Path $toPath "update"
        if (Test-Path -LiteralPath $copiedUpdateDir) {
            Remove-Item -LiteralPath $copiedUpdateDir -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function Wait-ForParentExit([int]$processId, [int]$timeoutSeconds = 120) {
    if ($processId -le 0) {
        return $true
    }

    $deadline = [DateTime]::UtcNow.AddSeconds($timeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        $parent = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($null -eq $parent) {
            return $true
        }
        Start-Sleep -Milliseconds 250
    }
    return $false
}

function Set-TerminalExit([int]$exitCode, [string]$message) {
    $script:finalExitCode = $exitCode
    $script:finalStatusMessage = $message
}

function Write-Journal([string]$phase, [string]$status, [string]$detail = "") {
    $entry = @{
        platform = "windows"
        session_id = $SessionId
        phase = $phase
        status = $status
        detail = $detail
        current_version = $CurrentVersion
        target_version = $TargetVersion
        manifest_path = $ManifestPath
        payload_path = $PayloadPath
        payload_sha256 = $PayloadSha256
        install_mode = $InstallMode
        install_target_path = $InstallTargetPath
        resolved_target_path = $resolvedTargetPath
        preserve_paths_csv = $PreservePathsCsv
        health_check_type = $HealthCheckType
        health_check_path = $HealthCheckPath
        timestamp_utc = [DateTime]::UtcNow.ToString("o")
    }
    ($entry | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath $journalPath -Encoding UTF8
    ($entry | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath $journalStepsPath -Encoding UTF8
}

function Resolve-TargetPath([string]$rawTarget) {
    if (-not $rawTarget) {
        return ""
    }
    $candidate = $rawTarget
    if (-not [System.IO.Path]::IsPathRooted($candidate)) {
        $candidate = Join-Path $RepoRoot $candidate
    }
    return [System.IO.Path]::GetFullPath($candidate)
}

function Test-IsAdministrator {
    try {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = New-Object Security.Principal.WindowsPrincipal($identity)
        return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch {
        return $false
    }
}

function Test-DirectoryWritable([string]$directoryPath) {
    try {
        if (-not (Test-Path -LiteralPath $directoryPath -PathType Container)) {
            New-Item -ItemType Directory -Path $directoryPath -Force | Out-Null
        }
        $probe = Join-Path $directoryPath ".llng-write-test-$([guid]::NewGuid().ToString('N')).tmp"
        [System.IO.File]::WriteAllText($probe, "probe", [System.Text.Encoding]::UTF8)
        Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue
        return $true
    } catch {
        return $false
    }
}

function Test-RequiresElevation([string]$targetPath) {
    if (-not $targetPath) {
        return $false
    }
    if (Test-Path -LiteralPath $targetPath) {
        $parent = Split-Path -Path $targetPath -Parent
        if (-not $parent) {
            return $true
        }
        return -not (Test-DirectoryWritable $parent)
    }
    $parent = Split-Path -Path $targetPath -Parent
    if (-not $parent) {
        return $true
    }
    return -not (Test-DirectoryWritable $parent)
}

function Invoke-ElevatedSelf {
    $args = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $scriptPath,
        "-ManifestPath", $ManifestPath,
        "-CurrentVersion", $CurrentVersion,
        "-TargetVersion", $TargetVersion,
        "-SessionId", $SessionId,
        "-PayloadPath", $PayloadPath,
        "-PayloadSha256", $PayloadSha256,
        "-InstallMode", $InstallMode,
        "-InstallTargetPath", $InstallTargetPath,
        "-PreservePathsCsv", $PreservePathsCsv,
        "-HealthCheckType", $HealthCheckType,
        "-HealthCheckPath", $HealthCheckPath,
        "-RepoRoot", $RepoRoot,
        "-ElevatedChild",
        "-ParentProcessId", $ParentProcessId
    )
    $process = Start-Process -FilePath "powershell" -ArgumentList $args -Verb RunAs -Wait -PassThru
    return [int]$process.ExitCode
}

function Resolve-StagedRoot([string]$extractedRoot) {
    $children = @(Get-ChildItem -LiteralPath $extractedRoot -Force)
    if ($children.Count -eq 1 -and $children[0].PSIsContainer) {
        return $children[0].FullName
    }
    return $extractedRoot
}

function Expand-PayloadToStaging([string]$sourcePayload, [string]$targetStagingDir) {
    if (Test-Path -LiteralPath $targetStagingDir) {
        Remove-Item -LiteralPath $targetStagingDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $targetStagingDir -Force | Out-Null

    $extractRoot = Join-Path $targetStagingDir "payload"
    New-Item -ItemType Directory -Path $extractRoot -Force | Out-Null

    if (Test-Path -LiteralPath $sourcePayload -PathType Container) {
        Copy-Item -LiteralPath $sourcePayload -Destination (Join-Path $extractRoot "content") -Recurse -Force
        return Resolve-StagedRoot (Join-Path $extractRoot "content")
    }

    $lower = $sourcePayload.ToLowerInvariant()
    if ($lower.EndsWith(".zip")) {
        Expand-Archive -Path $sourcePayload -DestinationPath $extractRoot -Force
        return Resolve-StagedRoot $extractRoot
    }
    if ($lower.EndsWith(".tar") -or $lower.EndsWith(".tar.gz") -or $lower.EndsWith(".tgz")) {
        $tar = Get-Command tar.exe -ErrorAction SilentlyContinue
        if ($null -eq $tar) {
            throw "tar.exe not found for tar payload extraction"
        }
        & $tar.Source -xf $sourcePayload -C $extractRoot
        if ($LASTEXITCODE -ne 0) {
            throw "tar extraction failed with code $LASTEXITCODE"
        }
        return Resolve-StagedRoot $extractRoot
    }
    throw "unsupported payload format for directory_swap: $sourcePayload"
}

function Test-PostUpdateHealth([string]$basePath) {
    if ($HealthCheckType -eq "none") {
        return $true
    }
    if ($HealthCheckType -eq "file_exists") {
        if (-not $HealthCheckPath) {
            return $false
        }
        $target = $HealthCheckPath
        if (-not [System.IO.Path]::IsPathRooted($target)) {
            $target = Join-Path $basePath $target
        }
        return (Test-Path -LiteralPath $target -PathType Leaf)
    }
    return $false
}

function Prune-BackupHistory([string]$root, [string]$keepSessionId) {
    if (-not (Test-Path -LiteralPath $root -PathType Container)) {
        return
    }
    $dirs = @(Get-ChildItem -LiteralPath $root -Directory | Sort-Object LastWriteTimeUtc -Descending)
    $kept = 0
    foreach ($dir in $dirs) {
        $hasCurrent = Test-Path -LiteralPath (Join-Path $dir.FullName "current") -PathType Container
        if ($dir.Name -eq $keepSessionId -and $hasCurrent) {
            $kept = 1
            continue
        }
        if ($hasCurrent -and $kept -lt 1) {
            $kept += 1
            continue
        }
        Remove-Item -LiteralPath $dir.FullName -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Output "[updater] start session=$SessionId current=$CurrentVersion target=$TargetVersion"
if (-not (Test-Path -LiteralPath $ManifestPath)) {
    Write-Output "[updater] manifest missing: $ManifestPath"
    Set-TerminalExit 2 "update failed: manifest missing"
    exit 2
}
if (-not (Test-Path -LiteralPath $PayloadPath)) {
    Write-Output "[updater] payload missing: $PayloadPath"
    Set-TerminalExit 4 "update failed: payload missing"
    exit 4
}
$actualSha = (Get-FileHash -Path $PayloadPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualSha -ne $PayloadSha256.ToLowerInvariant()) {
    Write-Output "[updater] payload checksum mismatch expected=$PayloadSha256 actual=$actualSha"
    Set-TerminalExit 5 "update failed: payload checksum mismatch"
    exit 5
}

if ($InstallMode -eq "directory_swap") {
    if (-not $InstallTargetPath) {
        Set-RuntimePaths $defaultJournalDir
        New-Item -ItemType Directory -Path $journalDir -Force | Out-Null
        Write-Journal -phase "swap" -status "failed" -detail "install_target_missing"
        Set-TerminalExit 8 "update failed: install target missing"
        exit 8
    }
    $resolvedTargetPath = Resolve-TargetPath $InstallTargetPath
    if (Test-PathWithin $defaultJournalDir $resolvedTargetPath) {
        $targetParent = Split-Path -Path $resolvedTargetPath -Parent
        if (-not $targetParent) {
            $targetParent = [System.IO.Path]::GetTempPath()
        }
        $externalJournalDir = Join-Path $targetParent ".llng-update-runtime\$SessionId\data\update"
        Set-RuntimePaths $externalJournalDir
        $runtimeMetadataOutsideTarget = $true
    } else {
        Set-RuntimePaths $defaultJournalDir
    }
    $requiresElevation = Test-RequiresElevation $resolvedTargetPath
    if ($requiresElevation -and -not (Test-IsAdministrator)) {
        if ($ElevatedChild) {
            New-Item -ItemType Directory -Path $journalDir -Force | Out-Null
            Write-Journal -phase "elevate" -status "failed" -detail "elevated_child_not_admin"
            Set-TerminalExit 12 "update failed: elevated child has no administrator token"
            exit 12
        }
        Write-Output "[updater] requesting elevation for target: $resolvedTargetPath"
        New-Item -ItemType Directory -Path $journalDir -Force | Out-Null
        Write-Journal -phase "elevate" -status "planned" -detail "uac_prompt"
        try {
            $elevatedExit = Invoke-ElevatedSelf
            if ($elevatedExit -eq 0) {
                Write-Journal -phase "elevate" -status "ok" -detail "elevated_apply_complete"
            } else {
                Write-Journal -phase "elevate" -status "failed" -detail "elevated_apply_failed"
            }
            if ($elevatedExit -eq 0) {
                Set-TerminalExit 0 "update completed successfully"
            } else {
                Set-TerminalExit $elevatedExit "update failed after elevation"
            }
            exit $elevatedExit
        } catch {
            Write-Journal -phase "elevate" -status "failed" -detail "elevation_denied"
            Set-TerminalExit 12 "update failed: elevation denied"
            exit 12
        }
    }
} else {
    Set-RuntimePaths $defaultJournalDir
}

New-Item -ItemType Directory -Path $journalDir -Force | Out-Null
if ($ParentProcessId -gt 0) {
    # Self-updates launched from the install root must wait until the app exits
    # or Windows will reject the directory rename during swap.
    Write-Output "[updater] waiting for parent process $ParentProcessId to exit"
    if (-not (Wait-ForParentExit -processId $ParentProcessId)) {
        Write-Journal -phase "handoff" -status "failed" -detail "parent_exit_timeout"
        Set-TerminalExit 13 "update failed: parent process did not exit in time"
        exit 13
    }
}

$lockStream = $null
try {
    $lockStream = [System.IO.File]::Open(
        $lockPath,
        [System.IO.FileMode]::CreateNew,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
    $activeLockPath = $lockPath
} catch {
    Write-Output "[updater] install lock active: $lockPath"
    Write-Journal -phase "lock" -status "failed" -detail "lock_active"
    Set-TerminalExit 7 "update failed: another updater session is active"
    exit 7
}
Write-Journal -phase "lock" -status "ok" -detail "lock_acquired"

try {
    Write-Journal -phase "verify" -status "ok" -detail "payload_checksum_verified"
    $stagedRoot = Expand-PayloadToStaging -sourcePayload $PayloadPath -targetStagingDir $stagingDir
    Write-Journal -phase "stage" -status "ok" -detail "payload_staged"

    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    $backupCurrent = Join-Path $backupDir "current"
    $swapped = $false

    if ($InstallMode -eq "directory_swap") {
        if (-not $resolvedTargetPath) {
            $resolvedTargetPath = Resolve-TargetPath $InstallTargetPath
        }
        $targetParent = Split-Path -Path $resolvedTargetPath -Parent
        if ($targetParent) {
            New-Item -ItemType Directory -Path $targetParent -Force | Out-Null
        }

        if (Test-Path -LiteralPath $backupCurrent) {
            Remove-Item -LiteralPath $backupCurrent -Recurse -Force
        }
        if (Test-Path -LiteralPath $resolvedTargetPath) {
            Move-Item -LiteralPath $resolvedTargetPath -Destination $backupCurrent -Force
            Remove-StaleUpdaterStateFromBackup -backupCurrentPath $backupCurrent
        }
        Write-Journal -phase "backup" -status "ok" -detail "backup_created"

        try {
            Move-Item -LiteralPath $stagedRoot -Destination $resolvedTargetPath -Force
            $swapped = $true

            $preservePaths = @()
            if ($PreservePathsCsv) {
                $preservePaths = $PreservePathsCsv.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ -and -not $_.StartsWith("/") -and -not $_.Contains("..") }
            }
            foreach ($relPath in $preservePaths) {
                if (-not (Test-Path -LiteralPath $backupCurrent)) {
                    break
                }
                $fromPath = Join-Path $backupCurrent $relPath
                if (-not (Test-Path -LiteralPath $fromPath)) {
                    continue
                }
                $toPath = Join-Path $resolvedTargetPath $relPath
                Copy-PreservedPath -fromPath $fromPath -toPath $toPath -relativePath $relPath
            }

            Write-Journal -phase "swap" -status "ok" -detail "directory_swap_complete"
            if (Test-PostUpdateHealth -basePath $resolvedTargetPath) {
                Write-Journal -phase "health" -status "ok" -detail "health_check_passed"
                Promote-RuntimeMetadataToTarget $resolvedTargetPath
            } else {
                Write-Journal -phase "health" -status "failed" -detail "health_check_failed"
                if (Test-Path -LiteralPath $resolvedTargetPath) {
                    Remove-Item -LiteralPath $resolvedTargetPath -Recurse -Force
                }
                if (Test-Path -LiteralPath $backupCurrent) {
                    Move-Item -LiteralPath $backupCurrent -Destination $resolvedTargetPath -Force
                    Promote-RuntimeMetadataToTarget $resolvedTargetPath
                    Write-Journal -phase "rollback" -status "ok" -detail "rollback_complete_after_health"
                } else {
                    Promote-RuntimeMetadataToTarget $resolvedTargetPath
                    Write-Journal -phase "rollback" -status "failed" -detail "rollback_source_missing_after_health"
                }
                Set-TerminalExit 11 "update failed health check and rollback was applied"
                exit 11
            }
        } catch {
            Write-Journal -phase "swap" -status "failed" -detail "directory_swap_failed"
            try {
                if ($swapped -and (Test-Path -LiteralPath $resolvedTargetPath)) {
                    Remove-Item -LiteralPath $resolvedTargetPath -Recurse -Force
                }
                if (Test-Path -LiteralPath $backupCurrent) {
                    Move-Item -LiteralPath $backupCurrent -Destination $resolvedTargetPath -Force
                    Promote-RuntimeMetadataToTarget $resolvedTargetPath
                    Write-Journal -phase "rollback" -status "ok" -detail "rollback_complete"
                } else {
                    Promote-RuntimeMetadataToTarget $resolvedTargetPath
                    Write-Journal -phase "rollback" -status "failed" -detail "rollback_source_missing"
                }
            } catch {
                Promote-RuntimeMetadataToTarget $resolvedTargetPath
                Write-Journal -phase "rollback" -status "failed" -detail "rollback_failed"
            }
            Set-TerminalExit 10 "update failed during directory swap"
            exit 10
        }
    } else {
        Write-Journal -phase "backup" -status "ok" -detail "backup_skipped_noop"
        Start-Sleep -Milliseconds 300
        Write-Journal -phase "swap" -status "ok" -detail "swap_placeholder_complete"
    }

    Prune-BackupHistory -root $backupRoot -keepSessionId $SessionId
    Write-Journal -phase "apply" -status "ok" -detail "apply_complete"
    # Keep per-session snapshot for diagnostics, but clear last-run marker after success
    # so stale recovery hints are not triggered by old completed runs.
    Remove-Item -LiteralPath $journalPath -Force -ErrorAction SilentlyContinue
    Write-Output "[updater] update apply complete"
    Set-TerminalExit 0 "update completed successfully"
    exit 0
} finally {
    if ($lockStream -ne $null) {
        $lockStream.Dispose()
    }
    if ($activeLockPath) {
        Remove-Item -LiteralPath $activeLockPath -Force -ErrorAction SilentlyContinue
    }
    if ($ParentProcessId -gt 0 -and $finalExitCode -ge 0) {
        if ($finalStatusMessage) {
            Write-Output "[updater] $finalStatusMessage"
        }
        Write-Output "[updater] this window will close in 10 seconds"
        Start-Sleep -Seconds 10
    }
}
