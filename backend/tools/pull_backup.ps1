# Layer 0 (off-host half) — pull the latest prod DB backup to this PC.
#
# This runs on an office PC, NOT on the server. It downloads the dump that
# tools/backup.sh produces, so a copy survives even if the host dies or the
# hosting account is suspended.
#
# ── ONE-TIME SETUP ─────────────────────────────────────────────────────────
# 1. Windows 10/11 already includes the OpenSSH `scp` client — nothing to
#    install. Confirm with:  scp        (should print usage, not "not found")
#
# 2. Create an SSH key so the scheduled task can run with no password prompt:
#       ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\id_ed25519"
#    Then add the PUBLIC key (id_ed25519.pub) to the server, either via
#    cPanel -> SSH Access -> Manage SSH Keys -> Import, or by appending it to
#    ~/.ssh/authorized_keys on the host.
#
# 3. Edit the CONFIG block below (SSH user + remote path).
#
# 4. Register the daily task (run once, in an Administrator PowerShell):
#       schtasks /Create /TN "GRP Costings Backup Pull" ^
#         /TR "powershell -ExecutionPolicy Bypass -File \"C:\path\to\pull_backup.ps1\"" ^
#         /SC DAILY /ST 09:00
#    Then open Task Scheduler -> that task -> Settings -> tick
#    "Run task as soon as possible after a scheduled start is missed"
#    so it still runs if the PC was off at 09:00.
# ───────────────────────────────────────────────────────────────────────────

$ErrorActionPreference = 'Stop'

# --- CONFIG: edit these --------------------------------------------------
$SshUser    = 'CHANGEME_cpaneluser'                       # cPanel SSH username
$SshHost    = 'faje.co.za'
$RemoteFile = '/home/CHANGEME_cpaneluser/backups/db_latest.sql.gz'
$KeyFile    = "$env:USERPROFILE\.ssh\id_ed25519"
$DestDir    = 'C:\Backups\GRP Costings'
$KeepDays   = 30                                          # local retention
# -------------------------------------------------------------------------

New-Item -ItemType Directory -Force -Path $DestDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$dest  = Join-Path $DestDir "db_$stamp.sql.gz"
$log   = Join-Path $DestDir 'pull.log'

try {
    & scp -i $KeyFile -o BatchMode=yes "$SshUser@${SshHost}:$RemoteFile" $dest
    if ($LASTEXITCODE -ne 0) { throw "scp exited with code $LASTEXITCODE" }

    # Rotate — drop local copies older than $KeepDays.
    Get-ChildItem $DestDir -Filter 'db_*.sql.gz' |
        Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$KeepDays) } |
        Remove-Item -Force

    "$(Get-Date -Format s)  pull OK -> $dest" | Add-Content $log
}
catch {
    "$(Get-Date -Format s)  pull FAILED: $_" | Add-Content $log
    exit 1
}
