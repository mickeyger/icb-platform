# ICB MES Server Install — Execution Log

**Server:** icb-mes-prod (192.168.0.251), ICB LAN + VPN
**OS:** Ubuntu 24.04.4 LTS (Noble), kernel 6.8.0-124, 15 GiB RAM / 4 vCPU / 98 GB disk
**Started:** 2026-06-22 (SAST)
**Operator (BA):** Michael
**Install CA:** Claude (Server-Install CA) — runbook `ICB_MES_Server_Install_Runbook_v1.0.md` + kickoff
**Access:** `ssh -i ~/.ssh/icb-platform icb@192.168.0.251` (icb = NOPASSWD operator); `mickeyger` = emergency (key-only).
**Host key:** `ED25519 SHA256:rdOolJ8IUM7T/8FYi3wtgLrqXVcJGrAtdOukiwDb7FU`

---

## Pre-flight

| Item | Status |
|---|---|
| Root/sudo | `icb` NOPASSWD sudo (bootstrapped by BA); `mickeyger` password-sudo |
| Hostname + IP | 192.168.0.251 → renamed `icb-mes-prod` |
| LAN CIDR | **192.168.0.0/24** (confirmed) |
| VPN CIDR + tech | TBC (Marnus) — ufw VPN rule deferred. ICBVPN/SSTP assigns clients 192.168.0.x (inside LAN /24) |
| SAP host + RO creds | TBC (Marnus) → blocks Layer 6 smoke test |
| icb deploy-user key | claude-code ed25519 installed |
| Backup dest (NAS) | TBC (Marnus) → Layer 7 off-box |
| TLS strategy | Self-signed (approved) |
| Internal DNS `mes.icb.internal` | TBC (Marnus) |

---

## §3.0 Discovery

- **Original box was Ubuntu 26.04** (Resolute Raccoon). Microsoft's `msodbcsql18` is **absent** from the 26.04 `resolute` pool (18 Azure/Intune pkgs only); present in 24.04 `noble` (`msodbcsql18` 18.5.1.1, `mssql-tools18` 18.6.1.1). Layer 6 is non-negotiable (ADR 0013) → **BA approved reimage to 24.04 LTS Noble.**
- **Post-reimage (24.04.4) discovery:** clean box — PG16 (`16.14`), Python 3.12.3, nginx 1.24 native; noble MS ODBC reachable; `/opt` empty; only `:22` listening; no stack packages. sudo password-gated (resolved via icb bootstrap).

---

## Layer 1 — Base OS  ✓ complete (BA signed off)

- **1.1** `apt full-upgrade` + base tools. Reboot-required flagged for **apparmor** (not kernel; running == latest kernel 6.8.0-124).
- **1.2** hostname `icb-mes-prod`; TZ `Africa/Johannesburg`; locale `en_ZA.UTF-8`; `/etc/hosts` 127.0.1.1 updated.
- **1.3** chrony active + synced (upstream `teraco.co.za`, Leap Normal).
- **1.4** `icb` deploy user (NOPASSWD sudo + key) — bootstrapped by BA to break the sudo chicken-and-egg.
- **1.5** SSH hardening `/etc/ssh/sshd_config.d/99-icb-hardening.conf` (`PermitRootLogin no`, `PasswordAuthentication no`, `PubkeyAuthentication yes`, `MaxAuthTries 3`, `ClientAlive 300/2`, `AllowUsers icb mickeyger`). Effective `sshd -T` verified.
- **1.6** ufw active, `deny incoming`, LAN `192.168.0.0/24` only on 22/443 (source-IP self-check passed).
- **1.7** fail2ban (sshd jail) + unattended-upgrades (`Automatic-Reboot "false"`).
- **Reboot-survives-hardening verified:** box rebooted (BA, 14:53) and returned with `passwordauthentication no`, ufw active, fail2ban/chrony/ssh active.

### Layer 1 deviations (→ runbook v1.1 patch candidates)
1. **Cloud-image SSH gotcha.** Reimaged cloud image shipped `/etc/ssh/sshd_config.d/50-cloud-init.conf` with `PasswordAuthentication yes`; sshd first-match-wins made it beat the `99-` hardening file → password auth silently stayed ON. Fixed: neutralized the directive + added `/etc/cloud/cloud.cfg.d/99-icb-ssh.cfg` (`ssh_pwauth: false`) for durability across cloud-init re-runs. **v1.1: runbook §1.5 must grep `sshd_config.d/` for pre-existing PasswordAuthentication before writing the 99-file.**
2. **Auto-rollback timers** (`systemd-run --on-active`) used for the 1.5/1.6 lockout-risk steps instead of the STEP A–H 3-session sequence — stateless, scriptable. **v1.1: adopt as standing pattern.**
3. **Non-interactive unattended-upgrades** config (wrote `20auto-upgrades` + set reboot false) instead of `dpkg-reconfigure -plow`. **v1.1: adopt.**

---

## Layer 2 — PostgreSQL 16  ✓ complete (BA signed off)

- **2.1** `postgresql-16` 16.14 + contrib; cluster online :5432.
- **2.2/2.4** tuning + WAL via drop-in `conf.d/10-icb-tuning.conf` (verified live): `shared_buffers 4GB`, `effective_cache_size 11GB`, `work_mem 32MB`, `maintenance_work_mem 1GB`, `wal_level replica`, `archive_mode on`, `archive_command` → `/var/backups/postgres/wal` (postgres-owned).
- **2.3** pg_hba: `host icb_platform icb_app 127.0.0.1/32 scram-sha-256` + `local all icb_admin peer`.
- **2.5** roles `icb_admin` (super), `icb_app`, `icb_readonly`; DB `icb_platform` (owner icb_admin); `search_path = icb_mes, icb_costings, public`. Schemas `icb_costings`/`icb_mes`/`icb_sap` created **owned by icb_app**. `icb_readonly` granted USAGE + default SELECT.
- **Verified:** app-user scram connectivity OK; **migration-readiness proven** (icb_app created/dropped tables in icb_mes + icb_sap and a view in icb_costings); search_path correct; WAL archiving live.
- **Passwords:** `icb_app`/`icb_readonly` generated (32-char alphanumeric), staged `/etc/icb/db_creds.env` (600 root:root) for Layer 5 `backend.env`. Postgres superuser password not set (peer/socket only) — kept off-disk per standing rule.

### Layer 2 deviation (BA-approved 20 Jun 2026)
Single `icb_app` role granted CREATE/ownership on all three schemas **including `icb_sap`**, contrary to runbook §2.5's ADR-0013 framing (which had `icb_sap` owned by icb_admin, icb_app SELECT-only). Reason: migrations run as `icb_app` and `0008` does `CREATE SCHEMA icb_sap AUTHORIZATION icb_app` + builds OITM/OITW/OWHS. **ADR-0013 runtime contract preserved** — the app code does not write to `icb_sap`; only the future ETL loader does. Tightening to DB-role level is a defence-in-depth enhancement, not a correctness fix.

**CA1 follow-up WO candidate (v4.36c.1, post-Burt-demo):** split `icb_app` → `icb_app_runtime` (SELECT-only on icb_sap; RW on icb_mes/icb_costings) + `icb_app_migration` (full; used by alembic + ETL only); point `backend/app/database.py` at the runtime role; alembic/ETL use the migration role. **ADR-0013 footnote (CA1 to write):** clarify the runtime-contract vs schema-ownership layers.

---

## Layer 3 — Application runtime  ✓ complete (signed off)
- Python deps (venv/dev, build-essential, libpq-dev, git); Node **v22.23.0** + npm 10.9.8 (NodeSource).
- Repo cloned → `/opt/icb-platform` (icb-owned, `main`); HEAD `0a83f82` (past v4.36a.5 / `3f188a3` ancestor).
- Backend venv: 50 wheels (uvicorn 0.42.0, fastapi 0.115.12, sqlalchemy 2.0.48). Frontend `npm install` + `npm run build` (`tsc -b && vite build`) → `dist/` (1.1 MB). No CA1-env divergence.

## Layer 4 — Nginx + TLS  ✓ complete (signed off)
- nginx 1.24.0; self-signed cert `CN=mes.icb.internal` (to 2031-06-21); site config (React static + `/api/` proxy + health), HTTP→HTTPS 301. Verified https/2 200, React shell served, `/healthz` proxy wired (502 until L5).
- **Deviations:** Option B (ufw 80/tcp from LAN, 301-shim); `/healthz`→`/health` nginx map (deviation #1 implemented); `listen 443 ssl http2` (1.24 syntax, not `http2 on;` which is 1.25.1+) → **v1.1 patch**.

## Layer 5 — systemd backend  ✓ complete (signed off)
- `/etc/icb/backend.env` (root:icb 600); `icb-backend.service` (uvicorn `app.main:app --app-dir backend`, 127.0.0.1:8000, 4 workers), enabled + running.
- `/health` 200 `{"status":"ok"}`; https `/healthz` 200 end-to-end; access logs in journal. Expected non-fatal: `Seed failed: relation "users" does not exist` (admin-seed pre-alembic; resolves after L8 + restart).
- **Deviations (runbook §5.1 env template wrong → v1.1 patches #6–#9):** `SESSION_SECRET` (not `SECRET_KEY`, REQUIRED — boot would fail), `ALLOWED_ORIGINS` (not `ALLOWED_HOSTS`), `DEPLOYMENT_MODE=on_prem` (not `ICB_ENV`), `SAP_DSN` dropped (`SAP_ENABLED=false`; app reads `icb_sap` from PG). `WorkingDirectory=/opt/icb-platform` + `--app-dir backend`.

## Layer 6 — SAP ODBC  ✓ complete (signed off); live smoke test TBC (Marnus)
- MS repo key → `/usr/share/keyrings/microsoft-prod.gpg` (signed-by pin; **v1.1 patch #10**, not `trusted.gpg.d`). `msodbcsql18` 18.6.2.1, `mssql-tools18`, `unixodbc` 2.3.12; `pyodbc` 5.3.0 in venv. `pyodbc.drivers()` = `['ODBC Driver 18 for SQL Server']`; `sqlcmd` on PATH.
- **TBC (Marnus):** live `sqlcmd -S <sap-host> -U <ro> … "SELECT TOP 1 * FROM OITM"`. ODBC path serves the SAP→`icb_sap` ETL loader, not the app runtime.

## Layer 7 — Backups + logrotate  ✓ complete (signed off); off-box NAS TBC (Marnus)
- `/usr/local/sbin/icb-pg-backup` (root:postgres 750): `runuser pg_dump -Fc | gzip` → `/var/backups/postgres` (chown root:postgres 600), **30-day retention** (simplified per BA vs fragile weekly predicate), audit entry → `backend/scripts_audit.log`.
- systemd `icb-pg-backup.{service,timer}` (next 02:30 daily); logrotate `/etc/logrotate.d/icb` (dry-run valid). Manual smoke test: dump produced (root:postgres 600, magic `PGDMP`), audit entry landed.
- **TBC (Marnus):** off-box NAS rsync (placeholder in script).

## Open TBC (Marnus → Michael), by blocking layer
- VPN pool CIDR + tech → ufw (post-L1)
- SAP host + RO creds → Layer 6
- NAS / off-box backup dest → Layer 7
- internal DNS `mes.icb.internal` → Layer 4/8

## Sign-off
| Layer | Verified | Date |
|---|---|---|
| Layer 1 — Base OS | ✓ | 2026-06-22 |
| Layer 2 — PostgreSQL | ✓ | 2026-06-22 |
| Layer 3 — Runtime | ✓ | 2026-06-22 |
| Layer 4 — Nginx/TLS | ✓ | 2026-06-22 |
| Layer 5 — systemd | ✓ | 2026-06-22 |
| Layer 6 — SAP ODBC | ✓ (smoke TBC) | 2026-06-22 |
| Layer 7 — Backups | ✓ (NAS TBC) | 2026-06-22 |
| Layer 8 — App deploy | ☐ | |
