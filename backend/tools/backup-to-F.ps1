# Daily backup of the Costing Model project to F:\Costing model
# Registered as scheduled task "Costing Model Daily Backup" (runs 18:00 daily).
# Idempotent: robocopy /E only copies changed files.

$ErrorActionPreference = 'Continue'

$projectRoot   = 'C:\Users\micge\Documents\Costing model'
$claudeProject = 'C:\Users\micge\.claude\projects\C--Users-micge-Documents-Costing-model'
$dest          = 'F:\Costing model'
$claudeDest    = Join-Path $dest '_claude_project_data'
$log           = Join-Path $dest '_backup.log'

function Write-Log {
    param([string]$msg)
    $line = '{0}  {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Write-Host $line
    try { Add-Content -Path $log -Value $line -ErrorAction Stop } catch { }
}

# --- Preflight: is F: mounted? ---
if (-not (Test-Path 'F:\')) {
    # Try to log to the local project tools dir as a fallback
    $fallback = Join-Path $projectRoot 'tools\backup-to-F.fallback.log'
    Add-Content -Path $fallback -Value ('{0}  F: drive NOT mounted -- backup skipped.' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
    exit 2
}

if (-not (Test-Path $dest)) {
    New-Item -ItemType Directory -Path $dest -Force | Out-Null
}

Write-Log '=== Backup starting ==='

# --- 1. Project tree ---
$rc1 = robocopy $projectRoot $dest /E /COPY:DAT /DCOPY:DAT /XD __pycache__ /R:1 /W:1 /NFL /NDL /NP /MT:16
$exit1 = $LASTEXITCODE
# Robocopy exit codes: 0=no change, 1=copied OK, 2=extras, 3=copied+extras, >=8=error
if ($exit1 -ge 8) {
    Write-Log ('Project robocopy FAILED (exit {0}).' -f $exit1)
} else {
    Write-Log ('Project robocopy OK (exit {0}).' -f $exit1)
}

# --- 2. Claude project data (memory + transcripts) ---
if (Test-Path $claudeProject) {
    $rc2 = robocopy $claudeProject $claudeDest /E /COPY:DAT /DCOPY:DAT /R:1 /W:1 /NFL /NDL /NP /MT:8
    $exit2 = $LASTEXITCODE
    if ($exit2 -ge 8) {
        Write-Log ('Claude data robocopy FAILED (exit {0}).' -f $exit2)
    } else {
        Write-Log ('Claude data robocopy OK (exit {0}).' -f $exit2)
    }
} else {
    Write-Log 'Claude project data folder not found - skipped.'
    $exit2 = 0
}

# --- Summary ---
try {
    $size = (Get-ChildItem $dest -Recurse -Force -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
    Write-Log ('Total backup size: {0:N1} MB' -f ($size / 1MB))
} catch { }

# Trim log to last 1000 lines to keep it tidy
try {
    if (Test-Path $log) {
        $lines = Get-Content $log -ErrorAction Stop
        if ($lines.Count -gt 1000) {
            $lines | Select-Object -Last 1000 | Set-Content $log
        }
    }
} catch { }

Write-Log '=== Backup finished ==='

# Exit non-zero only on real robocopy errors (>=8)
if ($exit1 -ge 8 -or $exit2 -ge 8) { exit 1 } else { exit 0 }
