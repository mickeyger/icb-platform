<#
.SYNOPSIS
    WO v4.21 (Phase 2D-2) — re-runnable ENTERPRISE PLANNING workbook ETL into icb_mes.

.DESCRIPTION
    Ensures migration 0006 is applied (nullable calc FK + source + carriers), then runs
    the one-shot loader (TRUNCATE icb_mes + reload from the workbook + re-seed the
    Materials/Buying/Stores master data from the mockup). Writes ONLY icb_mes; the Cost
    Calculator / icb_costings catalogue / faje are untouched. See
    docs/migrations/v4.21-workbook-load-report.md.

.PARAMETER Backup
    pg_dump -Fc the target DB before loading (rollback = pg_restore --clean).

.EXAMPLE
    pwsh backend/scripts/import_workbook.ps1 -Backup
#>
param(
    [string] $Workbook  = "$env:USERPROFILE\Documents\Burt Costing Model\ICB business process\ENTERPRISE PLANNING - 2026.xlsx",
    [string] $Today     = "",                                  # YYYY-MM-DD override for the active-job cutoff
    [switch] $Backup,
    [string] $BackupDir = "$env:USERPROFILE\Documents\icb_db_backups",
    [string] $PgBin     = 'C:\Program Files\PostgreSQL\18\bin',
    [string] $PgHost    = 'localhost',
    [string] $PgDb      = 'icb',
    [string] $PgUser    = 'icb_app',
    [string] $PgPass    = 'icb_app_dev'
)

$ErrorActionPreference = 'Stop'
$env:PGPASSWORD = $PgPass
$repo    = Split-Path -Parent (Split-Path -Parent $PSCommandPath)   # backend\.. = repo root
$backend = Join-Path $repo 'backend'
$py      = Join-Path $backend '.venv\Scripts\python.exe'

Write-Host "== WO v4.21 workbook ETL -> $PgUser@$PgHost/$PgDb ==" -ForegroundColor Green
Write-Host "   (TRUNCATEs all icb_mes tables, reloads from the workbook + re-seeds Materials)`n"

if (-not (Test-Path $Workbook)) { throw "workbook not found: $Workbook" }

# 0) Optional pre-load backup
if ($Backup) {
    if (-not (Test-Path $BackupDir)) { New-Item -ItemType Directory -Force $BackupDir | Out-Null }
    $dest = Join-Path $BackupDir 'icb_pre_import_workbook.dump'
    Write-Host "-- backup -> $dest" -ForegroundColor Cyan
    & (Join-Path $PgBin 'pg_dump.exe') -h $PgHost -U $PgUser -d $PgDb -Fc -f $dest
    if ($LASTEXITCODE -ne 0) { throw 'pg_dump backup failed' }
}

# 1) Ensure migration 0006 is applied (nullable calc_id + source + carrier columns)
Write-Host "-- alembic upgrade head" -ForegroundColor Cyan
Push-Location $backend
try {
    & '.\.venv\Scripts\alembic.exe' upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'alembic upgrade failed' }
} finally { Pop-Location }

# 2) Run the one-shot ETL (from the repo root, like seed_from_mockup)
$todayArg = if ($Today) { @('--today', $Today) } else { @() }
Write-Host "-- import_workbook" -ForegroundColor Cyan
Push-Location $repo
try {
    & $py -m backend.scripts.import_workbook --workbook $Workbook @todayArg
    if ($LASTEXITCODE -ne 0) { throw 'workbook ETL failed' }
} finally { Pop-Location }

Write-Host "`n== Done. Load report: docs/migrations/v4.21-workbook-load-report.md ==" -ForegroundColor Green
