#!/bin/bash
#
# Layer 0 — nightly backup of the GRP Costings app (runs ON the prod server).
#
# Deploy:
#   1. This file ships with the repo. After a deploy it lives at
#      ~/icecoldgrp/tools/backup.sh on the cPanel host.
#   2. Fill in the three DB_* values below from cPanel -> MySQL Databases
#      (or from the DATABASE_URL env var the app uses).
#   3. cPanel -> Cron Jobs, add (daily at 02:00):
#        0 2 * * * /bin/bash ~/icecoldgrp/tools/backup.sh >> ~/backups/cron.log 2>&1
#
# IMPORTANT: a backup that stays on this server is NOT disaster recovery.
# The companion tools/pull_backup.ps1 runs on an office PC and copies the
# dump OFF the host every day. Both halves are required.
#
set -euo pipefail

# cron runs with a minimal PATH — be explicit so mysqldump/gzip resolve.
export PATH=/usr/local/bin:/usr/bin:/bin:$PATH

# --- CONFIG: edit these three values ---------------------------------------
DB_USER="CHANGEME_dbuser"
DB_PASSWORD="CHANGEME_password"
DB_NAME="CHANGEME_dbname"
# ---------------------------------------------------------------------------

APP_DIR="icecoldgrp"          # app install folder under $HOME
BK="$HOME/backups"            # backup destination (kept OUTSIDE the app dir)
KEEP_DAYS=14                  # how long to retain local copies
STAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BK"

# 1. MySQL dump — consistent snapshot, includes stored routines.
mysqldump --single-transaction --quick --routines \
  -u "$DB_USER" -p"$DB_PASSWORD" "$DB_NAME" \
  | gzip > "$BK/db_${STAMP}.sql.gz"

# 2. App code + templates + uploads (in case the install itself is lost).
tar -czf "$BK/app_${STAMP}.tar.gz" -C "$HOME" "$APP_DIR" \
  --exclude="${APP_DIR}/tmp" \
  --exclude='*/__pycache__' \
  --exclude='*.pyc'

# 3. Fixed-name "latest" copy so the off-host pull script has a stable target.
cp -f "$BK/db_${STAMP}.sql.gz" "$BK/db_latest.sql.gz"

# 4. Rotate — delete local copies older than KEEP_DAYS.
find "$BK" -maxdepth 1 -name '*.gz' -mtime +"$KEEP_DAYS" -delete

echo "$(date '+%Y-%m-%d %H:%M:%S')  backup OK  ${STAMP}" >> "$BK/backup.log"
