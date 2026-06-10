# faje.co.za deploy runbook — Cost Calculator cutover to icb-platform (WO v4.30)

> **Status: code + deploy mechanics done; BLOCKED on a hosting DB-access constraint (§F).** §A/§C/§D/§E complete
> (path (c), `passenger_wsgi.py` bridge, two-phase parallel-app, per-phase rollback). Staging surfaced two infra
> blockers: **icb is Postgres but faje is MySQL** (needs a Postgres + a MySQL→Postgres migration), and HostAfrica's
> **egress firewall blocks outbound external DB ports** (external Postgres unreachable; a cPanel-LOCAL Postgres
> would sidestep it). Both in §F — gated on HostAfrica's local-PG / whitelist / upgrade reply. The MySQL→Postgres
> data migration is drafted in **§G** (needs a dry run before Phase 2). Pending: §F resolution + §G dry run, §B
> env VALUES, Phase 1 finish, Phase 2 paired, §3.5. Runbook for WO §0.4 / §0.5 / §0.7 / §3.2–§3.4.

Post-cutover, `faje.co.za` is served by **`mickeyger/icb-platform`** (was `GRP-Costing-System`). The Cost
Calculator (Jinja at `/`, `/calculator`, `/results/...`) is unchanged for users; the underlying repo changes.

---

## §A — Environment-variable contract (icb-platform)

Every backend env read goes through `backend/app/config.py` (`settings`). Two are **REQUIRED** (the app
refuses to boot without them); everything else has a safe default. Source of truth: `.env.example`.

| Key | Required | Default | faje cutover note |
|---|---|---|---|
| `DATABASE_URL` | **YES** | — | **PostgreSQL with the `+psycopg` driver:** `postgresql+psycopg://USER:PASS@HOST:PORT/DBNAME`. **Do NOT reuse the legacy `mysql+…` URL** — icb is Postgres-only (no PyMySQL → "No module named 'pymysql'"); plain `postgresql://` also fails (psycopg3 only). A Postgres DB reachable from HostAfrica must be provisioned + populated — **see §F**. |
| `SESSION_SECRET` | **YES** | — | Cookie/session signing key. **Re-use HostAfrica's current value** so existing UAT sessions don't all invalidate at cutover. |
| `DEPLOYMENT_MODE` | no | `cloud` | `cloud` for faje (surfaces in the UI footer). |
| `APP_PORT` | no | `8000` | Match HostAfrica's expected app port. |
| `AUTH_PROVIDER` | no | `email_password` | Keep `email_password`. |
| `FILE_STORE` | no | `./local_files` | Point at HostAfrica's persistent path if PDFs/uploads must survive redeploys. |
| `SMTP_URL` | no | `""` (no email) | Leave empty until v4.34 email notifications. |
| `SAP_ENABLED` / `SAP_BASE_URL` | no | `false` / `""` | Leave off (SAP is v4.33). |
| `DEFAULT_BRANCH_CODE` | no | `JHB` | Confirm faje's default branch with Michael. |
| `FEATURE_NEW_CALCULATOR` | no | `false` | Leave `false`. |
| `FRONTEND_DIST` | no | `<repo>/frontend/dist` | Only needed on deploy **path (a)** (full app serves the React MES at `/mes-app/`). Must point at a **built** `dist` (run `npm run build`). |
| `ANTHROPIC_API_KEY` | no | `""` (Help hidden) | Set it to keep the AI Help assistant the legacy app shipped; leave empty to hide it. |
| `ALLOWED_ORIGINS` | no | localhost set | Set to `https://faje.co.za` (+ any UAT host). Comma-separated or JSON array. |

**Pre-cutover task:** transcribe HostAfrica's current `GRP-Costing-System` env values into this contract (§B).
`SESSION_SECRET` maps 1:1; **`DATABASE_URL` does NOT** (legacy is MySQL, icb is Postgres — §F); rest take icb defaults.

## §B — HostAfrica env mapping  ⛔ PENDING ticket #2462727

Fill once Michael provides HostAfrica's current env panel (screenshot/copy-paste):

| HostAfrica current var | value (do NOT paste secrets here) | → icb key |
|---|---|---|
| `mysql+pymysql://…` (legacy) | **NOT reusable** | `DATABASE_URL` → **new Postgres**, see §F |
| _(current value)_ | reuse as-is | `SESSION_SECRET` |
| _(pending)_ | _(pending)_ | … |

## §C — Deploy path: (c) cPanel "Setup Python App" root-pointing  ✅ CONFIRMED (ticket #2462727)

HostAfrica's **Git deploy does NOT support subdirectory deploys**, but their **cPanel "Setup Python App"**
lets the Application root point at a subdirectory — **path (c)**, cleaner than the path-(b) wrapper because
**icb-platform stays as-is** (no `deploy/faje/` shim). Hosting is **cPanel + Phusion Passenger (WSGI)**.

**Passenger is WSGI-only; FastAPI is ASGI** — bridged by **`backend/passenger_wsgi.py`**, which wraps
`app.main:app` via `a2wsgi.ASGIMiddleware` and exposes it as the WSGI callable **`application`** (mirrors the
legacy `passenger_wsgi.py`; `a2wsgi==1.10.7` pinned in `backend/requirements.txt` — the version the legacy ran).

**cPanel Python Setup — current legacy → icb-platform target:**

| Field | Legacy (current) | icb-platform (cutover target) |
|---|---|---|
| Hosting | cPanel + Passenger (WSGI) | unchanged |
| Python version | 3.11.14 | 3.11 (icb runs on 3.11; CI uses 3.12) |
| Application root | `/home/fajecoza/icecoldgrp` | `/home/fajecoza/<icb-platform>/backend` (confirm on the day) |
| Application URL | `faje.co.za/` | unchanged |
| Startup file | `passenger_wsgi.py` | `passenger_wsgi.py` (now under `backend/`) |
| Entry point | `application` | `application` (the a2wsgi-wrapped ASGI app) |
| Virtualenv | `/home/fajecoza/virtualenv/icecoldgrp/3.11/` (persists, goes dormant) | **NEW venv auto-created from scratch** on root-change → first Pip Install takes several minutes |
| Pip install | manual "Run Pip Install" button | same — run after the pull (installs `a2wsgi`, etc.) |
| Restart | manual button | same — click after each change |

*(Acceptance: `/calculator` stays byte-identical to v4.29 except the intended v4.30 ports + the 55%-ratio
enhancement.)*

> **✅ RESOLVED (ticket #2462727, virtualenv):** changing the Application Root **creates a brand-new virtualenv
> from scratch — it does NOT reuse the existing one.** The `icecoldgrp` venv persists but goes **dormant**.
> Reverting the Root creates *yet another* new venv (it does **not** restore the original). A fresh venv's first
> **Pip Install takes several minutes.** Consequences:
> - **Cutover window: allocate ~30–45 min** at the cPanel (fresh pip install + verification), not 5–10.
> - **Rollback is heavier** for the in-place path — reverting Root = a new venv + a full re-pip-install + restart
>   (~10–15 min), not an instant flip. See §E for the safer parallel-app option.
>
> **✅ RESOLVED (ticket #2462727, final — parallel-app):** multiple Python apps ARE supported, but **one domain
> per app**. We can't bind both apps to faje.co.za at once — the workaround is a **subdomain** (e.g.
> `staging.faje.co.za`) for the new app, verify there, then **switch the URL** to the main domain. This makes
> the cutover a **two-phase** flow (§D): Phase 1 builds + verifies the new app on the subdomain (**zero
> production risk**); Phase 2 swaps the URLs (~5–10 min). **Parallel-app is the chosen path; the mutate-in-place
> steps are retained below only as a deep last-resort fallback.**

## §D — Cutover (paired with Michael, WO §3.4) — parallel-app, two phases

**Constraint:** HostAfrica supports multiple Python apps but **one domain per app** → build/verify on a
subdomain, then switch URLs.

### Phase 1 — build + verify the new app on a subdomain (ASYNCHRONOUS; faje.co.za UNAFFECTED)
Michael can do this solo — it doesn't touch production.
1. Create a **subdomain** (e.g. `staging.faje.co.za`).
2. Create a **new "Setup Python App"**: subdomain + Application Root `…/<icb-platform>/backend` + Python 3.11.14
   + startup `passenger_wsgi.py` + entry point `application`.
3. Configure **Git deploy** for `mickeyger/icb-platform` (branch `main`, post-merge) → the new app's directory; pull.
4. **Run Pip Install** — installs `backend/requirements.txt` (incl. `a2wsgi`) into the new app's fresh venv (several minutes).
5. **Restart + verify the subdomain** — `staging.faje.co.za/calculator`: log in, walk a costing, save a
   **discounted** quote + confirm **Net Total**, export Excel/PDF, check the dashboard. *(Run `alembic upgrade
   head` via the new venv if not wired to the deploy — 0015 is a no-op on the shared DB.)*
6. **Discover the URL mechanics** — in cPanel, find whether an existing app's domain/URL is **editable in place**
   or needs **delete + recreate**; this decides the Phase 2 swap. **Record the finding here.**

### Phase 2 — the actual cutover (PAIRED, ~5–10 min)
1. **Pre-cutover snapshot** — record the old `icecoldgrp` app's full config (§C table) = the rollback target.
2. **Release faje.co.za** from the old `icecoldgrp` app (URL edit or app delete, per the Phase 1 finding).
3. **Point the new app's URL** `staging.faje.co.za` → `faje.co.za`.
4. **Verify** on `faje.co.za/calculator` (same checks as Phase 1.5).
5. **Notify UAT testers** — "Cost Calculator now served from the unified codebase; behaviour unchanged; report issues."
6. **Park the old app ~48 h** as the safety net (don't delete its files) before §3.5 cleanup.

### Deep fallback — mutate-in-place (only if parallel-app is somehow unavailable on the day)
Repoint the existing app's Git source + Application Root in place (new venv → Run Pip Install → Restart). Window
~30–45 min; rollback ~10–15 min (revert both + re-pip-install — the original venv is not auto-restored). Avoid
unless forced; the parallel-app path keeps production on the old app until the URL swap.

## §E — Rollback (WO §0.7) — by phase

- **During Phase 1:** **no production risk** — faje.co.za is untouched. To abort, just delete the staging app +
  subdomain; nothing to revert.
- **During/after Phase 2 (~5–10 min):** **revert the URLs** — release `faje.co.za` from the new app and
  re-assign it to the **old `icecoldgrp` app**, which stays **parked + intact for ~48 h** (its venv + files
  unchanged → no rebuild). Re-point the new app to `staging.faje.co.za` if keeping it for a retry.
- **Deep-fallback (mutate-in-place) rollback:** revert Git source + Application Root + **re-pip-install** the
  fresh venv + restart (~10–15 min; the original venv is not auto-restored).

**No DB rollback** in any path — the only schema change (0015) is additive + guarded; the discount columns are
shared/faje-owned. Document the failure; iterate offline.

## §F — DATABASE: icb is Postgres, faje is MySQL — provisioning + data migration  ⚠ CUTOVER-CRITICAL

Surfaced at staging (Blocker 1): the live faje.co.za app runs **MySQL**; icb-platform is **PostgreSQL-only**
(the v4.12 migration). So the cutover is not just code+deploy — icb needs a **PostgreSQL DB, reachable from
HostAfrica, holding the calculator data.** The legacy `.env`'s `mysql+…` URL cannot be reused (→ "No module
named 'pymysql'").

### F.1 — Provision a Postgres reachable from HostAfrica
> **⚠ EGRESS BLOCK (confirmed at staging):** HostAfrica shared hosting **refuses outbound TCP to external DB
> ports** (`google.com:443` works; Supabase `5432`/`6543` → connection refused / RST). So an **external**
> managed Postgres is **unreachable** unless HostAfrica whitelists it / upgrades the plan. **A cPanel-LOCAL
> Postgres (`localhost`) is NOT subject to egress filtering** → it's the preferred path.

Order of preference:
1. **LOCAL cPanel PostgreSQL — PREFERRED (sidesteps egress entirely).** Ask HostAfrica: *"does this plan offer a
   local PostgreSQL (cPanel 'PostgreSQL Databases')?"* If yes, create a DB + user (full privileges so Alembic
   can make the `icb_mes`/`icb_costings` schemas); same box → host `localhost`, account-prefixed names:
   `postgresql+psycopg://fajecoza_icbapp:PASSWORD@localhost:5432/fajecoza_icbstaging`
2. **External managed Postgres** (Supabase/Neon/RDS) — only if HostAfrica **whitelists egress / upgrades**.
   `postgresql+psycopg://USER:PASS@<host>:5432/DBNAME` — currently **BLOCKED** by the egress firewall.
3. **Move hosting** to a Postgres-friendly provider — budget/lead-time decision (§F.5).

- The URL **must** carry `+psycopg` (psycopg3); plain `postgresql://` fails.

### F.2 — Create the schema (staging + prod), with the new DATABASE_URL in backend/.env
```
cd /home/fajecoza/icb-platform/backend && <venv>/bin/python -m alembic upgrade head
```
Creates the `icb_mes` + `icb_costings` schemas + all tables (0001→0015, incl. the discount columns via 0015).
An empty-but-migrated DB lets the app **boot** + the calculator **page** load, but with no
trailers/BOM/materials/formulas you can't actually cost.

### F.3 — Populate the data
- **Staging (fastest):** dump Michael's **local dev `icb` Postgres** (already a complete working dataset),
  restore to the staging DB, then `alembic stamp head`:
  ```
  # local:  pg_dump -Fc -h localhost -U icb_app -d icb -f icb.dump
  # server: pg_restore --no-owner --no-privileges -h localhost -U fajecoza_icbapp -d fajecoza_icbstaging icb.dump
  #         then:  <venv>/bin/python -m alembic stamp head
  ```
  (Dev data, not the latest live UAT — fine for the Phase-1 "boots + calculator loads" check.)
- **Prod cutover (the real migration — NEW WORKSTREAM):** the live data is in faje's **MySQL** and must be
  migrated **MySQL → Postgres** at cutover. ⚠ `migrate_to_postgres.py` in the legacy is **NOT** the tool (it
  reads SQLite). Use **pgloader** (MySQL→Postgres ETL, as v4.21 did for the catalogue) or a dump+transform,
  then `alembic stamp head`. **Needs its own mini-plan + a dry run before Phase 2** — the largest open cutover
  item. (Agent can draft it on request.)

### F.4 — Correction to earlier assumptions
The §A / ADR-0017 "shared DB; 0015 is a no-op on prod" framing held only for **local dev** (one Postgres for
calc + MES). In **prod** there is no shared Postgres yet: faje is MySQL, and the new prod Postgres is built by
Alembic — so **0015 CREATES the discount columns there** (not a no-op). The columns faje's MySQL got from the
d2da5bf deploy arrive in Postgres via the F.3 data migration + 0015.

### F.5 — If HostAfrica can't allow DB access: hosting options (decision for Burt)  ⛔ PENDING HostAfrica reply
Three outcomes from the egress ticket, by increasing disruption:

| Outcome | Unblocks | Cost / effort | Notes |
|---|---|---|---|
| **(a) LOCAL cPanel Postgres offered** | everything, no egress needed | lowest | **best case — confirm this FIRST** |
| **(b) Whitelist / plan upgrade for egress** | external managed Postgres (Supabase…) | low–med (paid upgrade → Burt budget) | depends on HostAfrica policy |
| **(c) Move hosting** (faje **+** MES) to a Postgres-friendly host | everything | highest (migrate site + DB + DNS) | last resort; longest lead time |

The MySQL→Postgres data migration (F.3) is **target-agnostic** — the same pgloader/dump approach applies
whether the Postgres ends up cPanel-local, whitelisted-external, or on a new host; only the connection string
changes. *(A fuller "hosting alternatives" comparison can be drafted if (c) becomes likely.)* Full plan in §G.

## §G — MySQL → PostgreSQL data migration plan (target-agnostic)  [WO §3.4 prerequisite]

Moves the live calculator data from faje's **MySQL** into the **PostgreSQL** the new app uses. Written so the
**target is a single connection string** — identical steps for §F.5 (a) cPanel-local / (b) whitelisted-external
/ (c) new-host; only `TARGET_PG_URL` changes.

### G.0 — Principle: Alembic owns the schema; pgloader moves DATA only
icb's schema (the `icb_costings` + `icb_mes` Postgres schemas, custom types, the `v_calculation_records_legacy`
view, the MES tables, constraints) is **owned by Alembic** — it must NOT be auto-created from MySQL's shape. So:
**(1)** build the exact schema with `alembic upgrade head`, then **(2)** load **data only** from MySQL into the
pre-created `icb_costings` tables with type casts. The `icb_mes.*` tables are calculator-irrelevant and stay
empty except the perm/branch rows migrations 0005/0013 seed.

### G.1 — Prerequisites
- A **read-only** MySQL user on faje's DB (pgloader only reads the source).
- The **target Postgres** from §F.1 (`TARGET_PG_URL`, `postgresql+psycopg://…`).
- **pgloader** on a host that can reach BOTH the MySQL and the target Postgres. ⚠ Mind the egress block (§F):
  if the target is **cPanel-local**, run pgloader **on the cPanel box** (localhost→localhost); if external, run
  from a host that can reach both.
- A **quiet window** or a consistent MySQL snapshot (no mid-write skew during the load).

### G.2 — Build the schema (target-agnostic), with `TARGET_PG_URL` in backend/.env
```
cd backend && <venv>/bin/python -m alembic upgrade head
```
→ creates `icb_costings` + `icb_mes` + all tables (0001→0015) AND writes `alembic_version` = head (the DB is
correctly stamped; no separate `stamp` in this flow — see G.5).

### G.3 — Load the data (pgloader, data-only)
pgloader `.load` file — **template; finalize the table list + casts against the live MySQL, then dry-run (G.7)**:
```
LOAD DATABASE
  FROM     mysql://RO_USER:PASS@MYSQL_HOST:3306/FAJE_DB
  INTO     postgresql://PG_USER:PASS@PG_HOST:5432/PG_DB   -- the ONE thing that changes per (a)/(b)/(c)
  WITH     data only, truncate, disable triggers, reset sequences, preserve index names
  SET      search_path to 'icb_costings'
  CAST     type datetime to timestamptz drop default using zero-dates-to-null,
           type tinyint  to boolean     using tinyint-to-boolean,
           type longtext to text
  INCLUDING ONLY TABLE NAMES MATCHING ~/^(calculations|customers|trailer_types|materials|formulas|bom_)/
  ALTER SCHEMA 'FAJE_DB' RENAME TO 'icb_costings'
;
```
Notes:
- `data only` + `truncate` → idempotent reruns into the Alembic-built tables (never clobbers the schema).
- `INCLUDING ONLY` the **calculator** tables — exclude any MySQL-only/legacy tables not in icb.
- icb-only columns absent in MySQL (e.g. `calculations.branch_id`, an MES-era addition) load as their PG
  default/NULL — `branch_id` NULL is expected + handled by the v4.29 **D1** fix on accept.
- `reset sequences` fixes the identity counters to `max(id)+1`.
- Fallback if pgloader can't be placed where both DBs are reachable: a Python ETL (SQLAlchemy reflect MySQL →
  insert via icb's models) — slower, no extra binary.

### G.4 — Verify (gate before Phase 2)
- **Row-count parity** per migrated table: MySQL `COUNT(*)` == Postgres `COUNT(*)`.
- **Spot-check** a recent quote end-to-end: dimensions, totals, **and `net_total` / `discount_*`** (proves the
  d2da5bf columns came across).
- **App smoke** on the new app: dashboard lists costings, open one, run a calculate, save a discounted quote.

### G.5 — `alembic stamp head` — when it's needed
**Not** needed here (G.2 `upgrade head` already stamped the DB). `alembic stamp head` is only for the
**alternative** where the schema arrives via `pg_restore` / pgloader-create (no migrations run) — then stamp so
Alembic knows the DB is at head without re-running. Never stamp a DB you built with `upgrade head`.

### G.6 — Rollback
- The **source MySQL is never written** (read-only) — it's the standing rollback for the whole cutover (the §E
  parallel-app URL revert keeps faje on the old MySQL app).
- The **target Postgres** is fresh/disposable: to redo, `DROP SCHEMA icb_costings CASCADE` (+ `icb_mes` if
  needed) and re-run G.2–G.3. No data is at risk — the authoritative copy stays in MySQL until Phase 2 + 48 h.

### G.7 — Dry run BEFORE Phase 2 (required)
Rehearse G.2–G.4 against the **staging** Postgres (or any throwaway target) on a recent MySQL copy. Confirm:
pgloader completes, **row counts match**, the discount spot-check passes, the calculator smoke passes — and
record the **wall-clock** (it sizes the Phase-2 window). Only schedule Phase 2 once a dry run is green.
