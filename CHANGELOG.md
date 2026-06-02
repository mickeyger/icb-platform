# Changelog

All notable changes to the ICB Platform monorepo are recorded here.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/).

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
