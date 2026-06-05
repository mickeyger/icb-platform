<#
.SYNOPSIS
    WO v4.22 (Phase 2D-3) — re-runnable multi-source ICB operational ETL into icb_mes.

.DESCRIPTION
    Ensures migrations are at head, then runs the one-shot loader (TRUNCATE icb_mes +
    reload). Sources: ENTERPRISE PLANNING (production_jobs/planning_slots), 01 - MRP 2026
    (demand_lines), 02 - Live Daily Count (live_daily_count), Book1 TRUCK REGISTER
    (chassis_register), + the mockup Materials re-seed. Writes ONLY icb_mes; the Cost
    Calculator / icb_costings catalogue / faje are untouched. The four workbook paths
    default inside import_workbook.py; override with the matching params if needed.

.PARAMETER Backup
    pg_dump -Fc the target DB before loading (rollback = pg_restore --clean).

.EXAMPLE
    pwsh backend/scripts/import_workbook.ps1 -Backup
#>
param(
    [string] $Planning = "",                                   # ENTERPRISE PLANNING workbook (default in py)
    [string] $Mrp      = "",                                   # 01 - MRP 2026.xlsx
    [string] $Ldc      = "",                                   # 02 - Live Daily Count 2026.xlsx
    [string] $Chassis  = "",                                   # Book1 TRUCK REGISTER 2026.xlsx
    [string] $Today    = "",                                   # YYYY-MM-DD override for the active-job cutoff
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
$backend = Split-Path -Parent (Split-Path -Parent $PSCommandPath)   # scripts\.. = backend
$repo    = Split-Path -Parent $backend                              # backend\.. = repo root
$py      = Join-Path $backend '.venv\Scripts\python.exe'

Write-Host "== WO v4.22 multi-source ETL -> $PgUser@$PgHost/$PgDb ==" -ForegroundColor Green
Write-Host "   (TRUNCATEs all icb_mes tables, reloads from MRP + Live Daily Count + Truck Register + JOBS)`n"

# 0) Optional pre-load backup
if ($Backup) {
    if (-not (Test-Path $BackupDir)) { New-Item -ItemType Directory -Force $BackupDir | Out-Null }
    $dest = Join-Path $BackupDir 'icb_pre_v422.dump'
    Write-Host "-- backup -> $dest" -ForegroundColor Cyan
    & (Join-Path $PgBin 'pg_dump.exe') -h $PgHost -U $PgUser -d $PgDb -Fc -f $dest
    if ($LASTEXITCODE -ne 0) { throw 'pg_dump backup failed' }
}

# 1) Ensure migrations at head (0007 adds live_daily_count + chassis_register)
Write-Host "-- alembic upgrade head" -ForegroundColor Cyan
Push-Location $backend
try {
    & '.\.venv\Scripts\alembic.exe' upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'alembic upgrade failed' }
} finally { Pop-Location }

# 2) Run the one-shot multi-source ETL (from the repo root)
$etlArgs = @()
if ($Planning) { $etlArgs += @('--planning', $Planning) }
if ($Mrp)      { $etlArgs += @('--mrp', $Mrp) }
if ($Ldc)      { $etlArgs += @('--ldc', $Ldc) }
if ($Chassis)  { $etlArgs += @('--chassis', $Chassis) }
if ($Today)    { $etlArgs += @('--today', $Today) }
Write-Host "-- import_workbook" -ForegroundColor Cyan
Push-Location $repo
try {
    & $py -m backend.scripts.import_workbook @etlArgs
    if ($LASTEXITCODE -ne 0) { throw 'workbook ETL failed' }
} finally { Pop-Location }

Write-Host "`n== Done. Load report: docs/migrations/v4.22-rescope-load-report.md ==" -ForegroundColor Green
