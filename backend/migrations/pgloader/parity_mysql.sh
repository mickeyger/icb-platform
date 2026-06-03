#!/usr/bin/env bash
# WO v4.20 — exact per-table row counts for the source grp_costings DB (MySQL side of
# the parity report). Emits `table|count` lines. Run in WSL:
#   tr -d '\r' < parity_mysql.sh | bash
set -uo pipefail
DB=grp_costings
MY="mysql -u migrate -pmigrate -h 127.0.0.1 -P 3307 -N -s"
for t in $($MY -e "SELECT table_name FROM information_schema.tables WHERE table_schema='$DB' ORDER BY table_name" 2>/dev/null); do
  c=$($MY -e "SELECT COUNT(*) FROM \`$DB\`.\`$t\`" 2>/dev/null)
  echo "$t|$c"
done
