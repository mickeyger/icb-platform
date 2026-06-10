# faje.co.za deploy runbook — Cost Calculator cutover to icb-platform (WO v4.30)

> **Status: §3.2 + deploy plan COMPLETE.** §A (env) + §C (path (c), `passenger_wsgi.py` ASGI→WSGI bridge,
> parallel-app confirmed) done; §D is the finalised **two-phase parallel-app** cutover (Phase 1 staging async →
> Phase 2 URL swap ~5–10 min), §E the per-phase rollback. Pending only EXECUTION: §B (env-var VALUES), Phase 1
> by Michael (async, no prod risk — incl. the URL-editable-vs-recreate finding), Phase 2 paired, then §3.5
> cleanup after ~48 h stable. Single runbook for WO §0.4 / §0.5 / §0.7 / §3.2–§3.4.

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
