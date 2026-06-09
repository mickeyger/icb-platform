# Changelog

All notable changes to the ICB Platform monorepo are recorded here.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased] — v4.30 Cost Calculator Unification Cutover

### Added
- Ported the 7-Jun edit-functionality release from `GRP-Costing-System` (`d2da5bf` + `14e6817`): per-quote
  **discount** (percent/amount → Net Total headline), **edit pending costings** (in-place overwrite or a new
  revision with faithful state replay), and **collapsible Excel Cost-Breakdown** sections with header subtotals.
- Migration **0015** — guarded (`ADD COLUMN IF NOT EXISTS`) discount columns on `icb_costings.calculations`
  (`discount_kind/input/amount`, `net_total`); a no-op on the shared prod DB, materialised on icb's own DBs.
- MES Costings surface `net_total` as the headline with a "before discount" breakdown when discounted
  (§0.2a); the Planning Board keeps pre-discount `selling_zar` as a workload metric.
- Calculator: a **new** costing defaults the Ratio to **55%**; edit/copy restore their saved/source ratio.
- `docs/migrations/v4.30-drift-audit.md` (drift register), `docs/runbooks/faje-deploy.md`
  (deploy/env/rollback), **ADR 0017** (cutover + parallel-codebase pattern), and a per-role cutover smoke
  journey (admin + sales).

### Notes
- Single source of truth: the live faje.co.za Cost Calculator moves to `icb-platform`; `GRP-Costing-System`
  is retired (archived). The HostAfrica Git-source switch + env mapping are the paired cutover step (§3.4),
  gated on ticket #2462727. `/calculator` stays byte-identical to v4.29 except the documented ports + the
  55%-ratio enhancement.

## [Unreleased] — Phase 1 foundation (WO v4.12)

### Added
- Monorepo skeleton: `backend/`, `frontend/`, `shared/`, `deploy/`, `db/`, `docs/`, `scripts/`.
- Cost Calculator imported into `backend/` (FastAPI + Jinja2), as-is.
- React MES mockup imported into `frontend/` (React 18 + Vite), served at `/mes-app/`.
- Single local PostgreSQL database `icb` with schemas `icb_costings` + `icb_mes`
  (`deploy/postgres/init.sql`).
- Alembic migration chain: `0001` baseline + `0002` `branches` table and nullable
  `branch_id` columns (backfilled to JHB).
- Environment-variable contract via `backend/app/config.py` (pydantic-settings) and
  `.env.example`; pluggable auth (`auth/`) and storage (`storage/`) Protocol interfaces.
- Windows-first dev scripts and a Linux + Windows CI matrix.
- ADRs 0001–0004.

### Notes
- Phase 1 is **local-dev only**. The live Cost Calculator at faje.co.za is unchanged.
