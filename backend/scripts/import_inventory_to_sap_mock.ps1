<#
.SYNOPSIS
    WO v4.23 — re-runnable icb_sap (SAP-mock) loader.

.DESCRIPTION
    Ensures migrations are at head, then runs the FK-safe UPSERT + soft-delete loader
    (WO v4.27 §3.6; replaces the v4.23 TRUNCATE+RELOAD): OWHS + OITM + OITW from 04 - Inventory 2026.xlsx, enriched
    from PRICE 2017 MARCH (08 April 2026).xlsx / Last P.P. Writes ONLY icb_sap; the Cost
    Calculator / icb_costings / faje are untouched.

.PARAMETER Backup
    pg_dump -Fc the target DB before loading (rollback = pg_restore --clean).

.EXAMPLE
    pwsh backend/scripts/import_inventory_to_sap_mock.ps1 -Backup
#>
param(
    [string] $Inventory = "",
    [string] $Price     = "",
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

Write-Host "== WO v4.23 icb_sap (SAP-mock) loader -> $PgUser@$PgHost/$PgDb ==" -ForegroundColor Green
Write-Host "   (UPSERT + soft-delete OITM/OITW/OWHS from Inventory + PRICE; FK-safe, no TRUNCATE)`n"

if ($Backup) {
    if (-not (Test-Path $BackupDir)) { New-Item -ItemType Directory -Force $BackupDir | Out-Null }
    $dest = Join-Path $BackupDir 'icb_pre_v423.dump'
    Write-Host "-- backup -> $dest" -ForegroundColor Cyan
    & (Join-Path $PgBin 'pg_dump.exe') -h $PgHost -U $PgUser -d $PgDb -Fc -f $dest
    if ($LASTEXITCODE -ne 0) { throw 'pg_dump backup failed' }
}

Write-Host "-- alembic upgrade head" -ForegroundColor Cyan
Push-Location $backend
try {
    & '.\.venv\Scripts\alembic.exe' upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'alembic upgrade failed' }
} finally { Pop-Location }

$etlArgs = @()
if ($Inventory) { $etlArgs += @('--inventory', $Inventory) }
if ($Price)     { $etlArgs += @('--price', $Price) }
Write-Host "-- import_inventory_to_sap_mock" -ForegroundColor Cyan
Push-Location $repo
try {
    & $py -m backend.scripts.import_inventory_to_sap_mock @etlArgs
    if ($LASTEXITCODE -ne 0) { throw 'icb_sap loader failed' }
} finally { Pop-Location }

Write-Host "`n== Done. Report: docs/migrations/v4.23-sap-mock-load-report.md ==" -ForegroundColor Green
