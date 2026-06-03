<#
.SYNOPSIS
    WO v4.20 (Phase 2D-1) — re-runnable MySQL -> PostgreSQL catalogue migration.

.DESCRIPTION
    Orchestrates the five ordered scripts in backend/migrations/pgloader/ plus the
    pgloader data-load (run inside WSL). Idempotent: re-running truncates the target
    costing catalogue and reloads it from the source. See docs/adr/0011-*.md for the
    full playbook and the production-cutover adaptation notes.

    PRECONDITIONS (one-time setup; see ADR 0011):
      * WSL2 with mirrored networking + pgloader installed.
      * The source dump restored into WSL MariaDB as DB 'grp_costings' on 127.0.0.1:3307,
        reachable by user migrate:migrate over TCP.
      * PostgreSQL running locally with the Phase-1 'icb' DB + icb_costings schema.

.PARAMETER Backup
    Take a pg_dump -Fc snapshot of the target DB before loading (rollback safety).

.EXAMPLE
    pwsh backend/scripts/migrate_catalogue.ps1 -Backup
#>
param(
    [switch] $Backup,
    [string] $PgBin     = 'C:\Program Files\PostgreSQL\18\bin',
    [string] $PgHost    = 'localhost',
    [string] $PgDb      = 'icb',
    [string] $PgUser    = 'icb_app',
    [string] $PgPass    = 'icb_app_dev',                       # non-superuser dev pw (same as .env)
    [string] $BackupDir = "$env:USERPROFILE\Documents\icb_db_backups"
)

$ErrorActionPreference = 'Stop'
$env:PGPASSWORD = $PgPass
$psql   = Join-Path $PgBin 'psql.exe'
$pgdump = Join-Path $PgBin 'pg_dump.exe'
$here   = Split-Path -Parent $PSCommandPath
$pgl    = (Resolve-Path (Join-Path $here '..\migrations\pgloader')).Path

# Translate a Windows path to its /mnt/<drive>/... WSL equivalent.
function ConvertTo-WslPath([string] $p) {
    $full = (Resolve-Path $p).Path
    '/mnt/' + $full.Substring(0,1).ToLower() + ($full.Substring(2) -replace '\\','/')
}
# Run a .sql file as the owner with ON_ERROR_STOP so any failure aborts the migration.
function Invoke-Psql([string] $file, [string] $label) {
    Write-Host "-- $label ($([IO.Path]::GetFileName($file)))" -ForegroundColor Cyan
    & $psql -h $PgHost -U $PgUser -d $PgDb -v ON_ERROR_STOP=1 -f $file
    if ($LASTEXITCODE -ne 0) { throw "psql step failed: $file" }
}

Write-Host "== WO v4.20 catalogue migration -> $PgUser@$PgHost/$PgDb ==" -ForegroundColor Green
Write-Host "   (this TRUNCATES the costing catalogue + all icb_mes, then reloads from MySQL)`n"

# 0) Optional pre-load backup (rollback = pg_restore --clean --if-exists --no-owner)
if ($Backup) {
    if (-not (Test-Path $BackupDir)) { New-Item -ItemType Directory -Force $BackupDir | Out-Null }
    $dest = Join-Path $BackupDir 'icb_pre_migrate.dump'
    Write-Host "-- backup -> $dest" -ForegroundColor Cyan
    & $pgdump -h $PgHost -U $PgUser -d $PgDb -Fc -f $dest
    if ($LASTEXITCODE -ne 0) { throw 'pg_dump backup failed' }
}

# 1) Clear the mock seed (preserves branches / alembic_version / skip-list)
Invoke-Psql (Join-Path $pgl '01_truncate_preload.sql') 'Pre-load truncate'
# 1b) Drop FKs (owner; no superuser needed) so source orphans can load
Invoke-Psql (Join-Path $pgl '01b_drop_fks.sql')        'Drop FK constraints'

# 2) pgloader data-only load (inside WSL)
$loadWsl = ConvertTo-WslPath (Join-Path $pgl 'grp_costings.load')
Write-Host "-- pgloader (WSL): $loadWsl" -ForegroundColor Cyan
wsl bash -c "pgloader '$loadWsl'"
if ($LASTEXITCODE -ne 0) { throw 'pgloader load failed' }

# 3) branch_id=JHB backfill + sequence reset
Invoke-Psql (Join-Path $pgl '02_post_load.sql')        'Post-load backfill + sequences'
# 4) Re-add FKs (VALID where clean, NOT VALID where source orphans)
Invoke-Psql (Join-Path $pgl '03_readd_fks.sql')        'Re-add FK constraints'

# 5) Parity check (PG side via psql; MySQL side via WSL)
Write-Host "`n== Parity: PostgreSQL (icb_costings) ==" -ForegroundColor Green
& $psql -h $PgHost -U $PgUser -d $PgDb -f (Join-Path $pgl 'parity_pg.sql')
Write-Host "`n== Parity: MySQL source (grp_costings) ==" -ForegroundColor Green
$parityWsl = ConvertTo-WslPath (Join-Path $pgl 'parity_mysql.sh')
wsl bash -c "tr -d '\r' < '$parityWsl' | bash"

Write-Host "`n== Migration complete. Compare the two parity tables above. ==" -ForegroundColor Green
Write-Host "   See docs/migrations/v4.20-parity-report.md for the signed-off comparison."
