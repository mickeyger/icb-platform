# faje.co.za deploy runbook — Cost Calculator cutover to icb-platform (WO v4.30)

> **Status: §3.2 DONE.** §A (env contract) + §C (deploy **path (c)** confirmed via ticket #2462727 + the
> `passenger_wsgi.py` ASGI→WSGI bridge) complete; §D/§E cutover + rollback steps are written. Still pending:
> §B (the actual env-var VALUES from Michael), the **virtualenv-reuse** answer (§C open question), and §D
> **execution** in the paired §3.4 session. Single runbook for WO §0.4 (deploy), §0.5 (env), §0.7 (rollback), §3.2–§3.4.

Post-cutover, `faje.co.za` is served by **`mickeyger/icb-platform`** (was `GRP-Costing-System`). The Cost
Calculator (Jinja at `/`, `/calculator`, `/results/...`) is unchanged for users; the underlying repo changes.

---

## §A — Environment-variable contract (icb-platform)

Every backend env read goes through `backend/app/config.py` (`settings`). Two are **REQUIRED** (the app
refuses to boot without them); everything else has a safe default. Source of truth: `.env.example`.

| Key | Required | Default | faje cutover note |
|---|---|---|---|
| `DATABASE_URL` | **YES** | — | The **shared** Postgres (`postgresql+psycopg://…/icb`, schemas `icb_costings` + `icb_mes`). Re-use HostAfrica's existing calculations DB connection — the discount columns already exist there (faje's d2da5bf deploy + migration 0015 is a no-op on it). |
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

**Pre-cutover task:** transcribe HostAfrica's current `GRP-Costing-System` env values into this contract
(§B) — most map 1:1 (`DATABASE_URL`, `SESSION_SECRET`); the rest take icb defaults.

## §B — HostAfrica env mapping  ⛔ PENDING ticket #2462727

Fill once Michael provides HostAfrica's current env panel (screenshot/copy-paste):

| HostAfrica current var | value (do NOT paste secrets here) | → icb key |
|---|---|---|
| _(pending)_ | _(pending)_ | `DATABASE_URL` |
| _(pending)_ | _(pending)_ | `SESSION_SECRET` |
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
| Virtualenv | `/home/fajecoza/virtualenv/icecoldgrp/3.11/` | ⚠ see open question below |
| Pip install | manual "Run Pip Install" button | same — run after the pull (installs `a2wsgi`, etc.) |
| Restart | manual button | same — click after each change |

*(Acceptance: `/calculator` stays byte-identical to v4.29 except the intended v4.30 ports + the 55%-ratio
enhancement.)*

> **⚠ OPEN (Michael → HostAfrica):** does changing the Application root **reuse** the existing virtualenv at
> `/home/fajecoza/virtualenv/icecoldgrp/3.11/`, or create a NEW one? Affects rollback (a fresh venv leaves the
> old one intact for revert; a reused/mutated venv must be re-pip-installed on rollback). Doesn't block §3.2.
> Record the answer here.

## §D — Cutover steps (paired session, WO §3.4) — TWO cPanel config changes

1. **Pre-cutover snapshot** — record (a) the current `GRP-Costing-System` commit deployed, and (b) ALL current
   Python Setup field values (table above) = the rollback target.
2. **Switch Git source** — cPanel Git deploy: repo `mickeyger/GRP-Costing-System` → `mickeyger/icb-platform`,
   branch `main` (post-merge); pull.
3. **Update Application root** — Python Setup: `…/icecoldgrp` → `…/<icb-platform>/backend` (confirm the on-disk path).
4. **Run Pip Install** — click the button → installs `backend/requirements.txt` (incl. `a2wsgi`). *(Not automatic on Git pull.)*
5. **Restart** — click the Restart button (required after code/config change).
6. **Verify** — `faje.co.za/calculator`: log in as a UAT user, walk a costing, save a **discounted** quote and
   confirm **Net Total** displays correctly, export Excel/PDF, check the dashboard. Confirm zero behavioural diff.
   *(Run `alembic upgrade head` via the venv if it isn't wired to the deploy — applies 0015, a no-op on the shared DB.)*
7. **Notify UAT testers** — "Cost Calculator now served from the unified codebase; behaviour unchanged; report issues."

## §E — Rollback (WO §0.7) — reverse BOTH cPanel changes

If any step fails, in cPanel: **(1)** revert the **Git source** to `mickeyger/GRP-Costing-System` + pull the
pre-cutover commit (§D.1); **(2)** revert the **Application root** to `/home/fajecoza/icecoldgrp`; **(3) Run Pip
Install** (restores the legacy deps — esp. if the virtualenv was reused, see the open question); **(4) Restart**.
**No DB rollback** — the only schema change (0015) is additive + guarded; the discount columns are
shared/faje-owned. Document the failure; iterate offline.
