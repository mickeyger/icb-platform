# ADR 0011 — MySQL → PostgreSQL catalogue migration (pgloader playbook)

- **Status:** Accepted
- **Date:** 2026-06-03
- **Work order:** v4.20 (Phase 2D-1)
- **Supersedes mock seed for:** `icb_costings.*` (the costing domain) on the local/UAT DB

## Context

Phase 2C wired every React MES screen to live PostgreSQL, but the costing catalogue it
read was the **mock seed** (`seed_from_mockup.py`, ADR 0007). Phase 2D's goal is
functional readiness against **real ICB operations data**, so the local/UAT
`icb_costings` schema must hold the actual faje UAT catalogue.

- **Source:** `fajecoza_grp_costings.sql` — a `mysqldump` of faje's live `grp_costings`
  MySQL DB (the Cost Calculator's production data: 794 materials, 8 984 BOM rows,
  2 183 customers, 5 158 SAP item codes, 6 historical calculations, …).
- **Target:** the existing local **PostgreSQL 18** DB `icb`, schema `icb_costings`,
  owned by the **non-superuser** role `icb_app`. The Phase-1 schema already models these
  43 tables (it was reverse-engineered from this same costing app), so this is a
  **data-only** load into an existing schema — **no DDL**.
- **Hard constraints (BA):** the Jinja **`/calculator` must stay regression-free** (the
  gate); **don't touch faje.co.za**; **don't touch v4.13–v4.19 application logic** (data
  load only); **`pg_dump` backup before the load** (rollback = restore); the postgres
  superuser password is **local-only, never written to disk/commits/.env**.

This ADR is intended to double as the **reusable playbook for the eventual faje
production cutover** (Postgres becomes the system of record). Capture everything.

## Decision

### Approach: pgloader, run from WSL (BA §0.1 = Option A)

`pgloader` is the right tool — it reads a live MySQL/MariaDB source and streams into
PostgreSQL with automatic type coercion. It does not run natively on Windows, so it runs
inside **WSL2 Ubuntu**. The Python-csv fallback (§0.1 Option B) was kept in pocket but
**not needed** — WSL + pgloader worked.

**Toolchain (record exact versions for reproducibility):**

| Component | Version / detail |
|---|---|
| WSL2 | Ubuntu 24.04, **mirrored networking** (`%USERPROFILE%\.wslconfig` → `[wsl2]\nnetworkingMode=mirrored`); Windows build 26200 |
| MariaDB (in WSL) | 11.8.6, listening on **port 3307** (a Windows `mysqld` already holds 3306, and mirrored networking shares the port namespace) |
| pgloader (in WSL) | 3.6.10 |
| PostgreSQL | 18 (Windows host), DB `icb`, role `icb_app` (**non-superuser** owner) |
| MySQL access user | `migrate:migrate` over TCP (the dump's `root` is `unix_socket`-only) |

### Load procedure (5 ordered scripts in `backend/migrations/pgloader/`)

The whole sequence is also wrapped by `backend/scripts/migrate_catalogue.ps1`.

1. **`01_truncate_preload.sql`** (owner `icb_app`) — clear the mock seed so the load is
   clean: truncate all 43 in-scope `icb_costings` tables + **all** `icb_mes` tables,
   `RESTART IDENTITY CASCADE`. **Preserve** `branches`, `alembic_version`, and the
   skip-list tables. (icb_mes is cleared too so reloaded calculations don't orphan stale
   mock production jobs — MES dashboards are intentionally empty until v4.21.)

2. **`01b_drop_fks.sql`** (owner `icb_app`) — **drop all FK constraints first**, saving
   their definitions to `icb_costings._fk_backup`. *Why:* the source has orphan rows (see
   Drift), and inserting them with FKs live would fail RI triggers. pgloader's own
   `disable triggers` requires **superuser** (it disables *system* RI triggers) and
   errors `42501` for `icb_app`. The owner **can** drop/re-add its own FKs without
   superuser — so we drop-before / re-add-after instead. This keeps the superuser
   password off-disk (constraint satisfied).

3. **`grp_costings.load`** (pgloader, run inside WSL) — **data-only** load:
   ```
   LOAD DATABASE
        FROM mysql://migrate:migrate@127.0.0.1:3307/grp_costings
        INTO postgresql://icb_app:icb_app_dev@127.0.0.1:5432/icb
    WITH data only, create no tables, create no indexes, no truncate,
         batch rows = 2000, prefetch rows = 2000
    EXCLUDING TABLE NAMES MATCHING ~/^user_sessions$/, ~/^help_request_log$/
    ALTER SCHEMA 'grp_costings' RENAME TO 'icb_costings';
   ```
   - `data only` + `create no tables`/`no indexes` → insert into the **existing**
     Phase-1 schema; never touch DDL.
   - `ALTER SCHEMA … RENAME` maps the MySQL DB name onto our PG schema.
   - **Skip-list:** `user_sessions` (ephemeral login state) + `help_request_log`
     (operational log) — not catalogue data.

4. **`02_post_load.sql`** (owner) — two DO blocks:
   - **`branch_id = JHB` backfill** on every branch-scoped **base table** (Phase-1
     single-branch parity). *Gotcha:* `information_schema.columns` includes the
     `v_calculation_records_legacy` **view**, which can't be `UPDATE`d — filter to
     `table_type = 'BASE TABLE'`.
   - **Sequence reset** — `setval` every owned `icb_costings` sequence to `MAX(id)+1`
     (belt-and-suspenders to pgloader's own sequence reset).

5. **`03_readd_fks.sql`** (owner) — re-add the 53 FKs from `_fk_backup`. Try `VALID`
   first; on failure (source orphans) re-add **`NOT VALID`** (enforces *new* writes,
   tolerates the existing orphan rows — matching faje's live behaviour). Logs which went
   NOT VALID, then drops `_fk_backup`.

### Type casting

Because this is a **data-only load into the existing Phase-1 schema**, we rely on
**pgloader's default MySQL→PostgreSQL casts** to coerce source values into the
already-correct PG column types (the Phase-1 schema was modelled on this same source):
`tinyint(1) → boolean`, `datetime → timestamp`, `decimal → numeric`, `text/varchar →
text/varchar`, MySQL `0000-00-00` zero-dates → `NULL`. **No custom `CAST` rules were
needed** and the load reported **0 cast/insert errors**. (If a future source revision
adds a column whose MySQL type doesn't map cleanly to the existing PG type, add an
explicit `CAST` clause to `grp_costings.load` rather than changing the schema.)

## Drift findings (source data quality)

**357 of 8 984 `bill_of_materials` rows (4.0%) are orphans** — they reference parent ids
that don't exist in the source. faje's MySQL had relaxed FK enforcement, so these were
never rejected. They migrate **as-is**, isolated behind `NOT VALID` FKs. **No row was
dropped or altered to make the load succeed.**

| FK (all on `bill_of_materials`) | Orphan rows | Missing parent id(s) |
|---|---:|---|
| `…_trailer_type_id_fkey` | 202 | 51 |
| `…_bom_section_id_fkey` | 112 | 1,2,3,4,5,6,7,9,10,11 |
| `…_body_option_group_id_fkey` | 22 | 21 |
| `…_body_option_subgroup_id_fkey` | 21 | 45,55,59,62 |

→ When faje cleans these (or a later WO reloads with corrected refs),
`ALTER TABLE … VALIDATE CONSTRAINT …` promotes them to fully `VALID`.

## Verification

- **Row-count parity:** all **43 data tables match the source exactly**; Σ source rows
  (excl. skip-list) = **28 580** = pgloader's reported import total (independent
  cross-check). Full table in `docs/migrations/v4.20-parity-report.md`.
- **`/calculator` regression (the gate) — all green:**
  - Backend **boots clean** against the migrated DB (ORM ↔ migrated schema compatible;
    no column drift).
  - `/calculator` renders; `/api/session` authenticates the migrated `admin`; the
    **6 historical UAT calculations** surface in `/api/calculations` with real
    customer/trailer/total data.
  - `/api/calculate` runs the real formula engine over migrated BOM — **deterministic**
    (same input → same output) and works across the catalogue (RIGID DRY FREIGHT, MEAT
    BODY, FREEZER, … all 200, coherent totals).
  - A fresh minimal recompute of a historical quote legitimately differs from its stored
    total **only because of un-replayed interactive inputs** (item-set + a
    `category_multipliers` like `{"SIDES":2.0}`, frozen in `result_json` but not in
    `dimensions_json`) — **not data drift**. The stored result is internally consistent
    (`Σ category_totals == grand_total`, `selling == cost × (1+margin)`).
- **SPA unaffected:** `/api/mes/autologin` still mints an `admin` session by username
  (no password dependency), so the React app authenticates post-migration. MES
  dashboards are intentionally empty until v4.21.

## Consequences

- **Local/UAT now runs on real catalogue data**; the mock seed is superseded there (it
  remains the bootstrap for a fresh empty DB / CI).
- **First-boot seed self-heal (expected, non-catalogue):** the idempotent `seed()` adds
  only the inactive "Light" theme (`themes` 3→4); `users`/`admin_settings`/catalogue are
  untouched. Documented in the parity report.
- **Reusable for the faje production cutover.** The same five scripts apply; for the real
  cutover, change only: (a) the source connection/dump, (b) **drop the `branch_id=JHB`
  backfill** once true multi-branch data exists, (c) decide the skip-list per environment,
  (d) run a fresh `pg_dump` backup first, (e) schedule a maintenance window + restore-based
  rollback. The non-superuser drop-FK/re-add pattern means **no superuser password is ever
  needed on the migration host**.
- **Rollback:** `pg_restore --clean --if-exists --no-owner` from the pre-load
  `pg_dump -Fc` backup (`icb_db_backups/icb_pre_v420.dump`) restores the prior state
  (verified during this WO when recovering pristine FKs).
- **WSL networking lesson:** WSL→Windows-Postgres over the default NAT subnet is blocked
  by the Windows firewall even with PG `listen_addresses='*'`; **mirrored networking**
  (`127.0.0.1` shared) is the clean fix on Windows 11 22H2+/build 26200. It does mean WSL
  and Windows **share the port namespace** — hence MariaDB on 3307.
