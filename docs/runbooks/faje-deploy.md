# faje.co.za deploy runbook — Cost Calculator cutover to icb-platform (WO v4.30)

> **Status: WIP.** §A (env contract) is complete. §B (HostAfrica mapping), §C (deploy path), §D (cutover)
> and the rollback drill are **gated on HostAfrica ticket #2462727** — finalised in the paired §3.4 session.
> This is the single runbook referenced by WO §0.4 (deploy), §0.5 (env), §0.7 (rollback) and §3.2–§3.4.

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

## §C — Deploy path (a vs b)  ⛔ PENDING HostAfrica subdirectory-deploy capability

- **Path (a) — subdirectory deploy supported:** point HostAfrica's Git pull at **`backend/`** as the deploy
  root; entry `app.main:app` (uvicorn/gunicorn). Serves the full unified app (calculator + MES). Requires a
  built `frontend/dist` (or `FRONTEND_DIST`) for `/mes-app/`. Simplest if supported.
- **Path (b) — repo-root entry only:** add a thin `deploy/faje/` wrapper importing **only** the Cost
  Calculator routers (no React MES). Build + verify it serves `/calculator` standalone before cutover.

Decision recorded here once Michael confirms. *(Acceptance: whichever path, `/calculator` stays
byte-identical to v4.29 except the intended v4.30 ports + the ratio-default enhancement.)*

## §D — Cutover steps (paired session, WO §3.4)  ⛔ PENDING

1. **Pre-cutover snapshot** — note the current `GRP-Costing-System` commit deployed on faje (fallback target).
2. **Optional staging** — if HostAfrica has a staging path, deploy icb-platform there + verify first.
3. **Switch Git source** — HostAfrica panel: repo `mickeyger/GRP-Costing-System` → `mickeyger/icb-platform`, branch `main` (post-merge).
4. **Pull + deploy** — trigger the Git pull; watch logs. `alembic upgrade head` runs (0015 is a no-op on the shared DB).
5. **Verify** — load `/calculator`, log in as a UAT user, walk a costing, save a discounted quote (Net Total), export Excel/PDF. Confirm zero behavioural diff.
6. **Notify UAT testers** — "Cost Calculator now served from the unified codebase; behaviour unchanged; report issues."

## §E — Rollback (WO §0.7)

If any step fails: in the HostAfrica panel revert the Git source to `mickeyger/GRP-Costing-System` and pull
the pre-cutover commit (from §D.1). **No DB rollback needed** — the cutover makes no destructive schema change
(0015 is additive + guarded; the discount columns are shared/faje-owned). Document the failure; iterate offline.
