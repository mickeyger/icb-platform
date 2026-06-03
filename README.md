# ICB Platform

Unified codebase for **Icecold Bodies**: the Cost Calculator (FastAPI + Jinja2) and the
Manufacturing Execution System (React + Vite) served from a **single FastAPI service**.
One git commit runs in two deployment modes — **cloud** (dev/staging + off-site reps) and
**on-prem** (Icecold's primary production target) — selected entirely by environment variables.

> **Status:** Phase 1 (foundation). See `docs/adr/` and the Unified Codebase Plan.
> Phase 1 is **local-dev only**; the live Cost Calculator at faje.co.za is untouched.

---

## Architecture at a glance

```
icb-platform/
├── backend/        FastAPI app (app/), Alembic migrations (alembic/), tests/
├── frontend/       React 18 + TypeScript + Vite (MES UI)
├── shared/         Cross-language type definitions (populated in a later phase)
├── deploy/         postgres/init.sql · docker/ (Phase 2) · windows/ (Phase 3)
├── db/             Schema reference docs (migrations live in backend/alembic/versions)
├── docs/adr/       Architecture Decision Records
└── scripts/        setup / start / start-dev (.bat for Windows, .sh for Linux/Mac)
```

- **One PostgreSQL 16 database** (`icb`) with two schemas: `icb_costings` and `icb_mes`.
- **One FastAPI service on port 8000.** Jinja routes (`/`, `/calculator`, `/mes/*`) and the
  React SPA (`/mes-app/*`) are served by the same process.
- **All configuration via environment variables** — see `.env.example` and `backend/app/config.py`.

## Prerequisites

| Tool | Version used here |
|------|-------------------|
| Python | 3.12+ (3.14 supported) |
| Node.js | 20+ (24 used) |
| PostgreSQL | 18 |
| Git | 2.40+ |

> On this dev machine PostgreSQL **18 listens on port `5432`**.
> The port is set by `DATABASE_URL` in `.env` — change it freely.

## First-time setup (Windows)

```bat
:: 1. Create the database (run once, as the postgres superuser)
"C:\Program Files\PostgreSQL\18\bin\psql.exe" -p 5432 -U postgres -f deploy\postgres\init.sql

:: 2. Copy and edit your local env file
copy .env.example backend\.env

:: 3. Install deps, build the frontend, apply migrations, seed
scripts\setup.bat
```

## Run

```bat
scripts\start.bat        :: production-like: single FastAPI service on http://localhost:8000
scripts\start-dev.bat    :: hot-reload: FastAPI:8000 + Vite:5173 (Vite proxies /api -> 8000)
```

Then visit:

| URL | What |
|-----|------|
| http://localhost:8000/calculator | Jinja Cost Calculator (parity with faje.co.za) |
| http://localhost:8000/ | Jinja dashboard |
| http://localhost:8000/mes/dashboard | Jinja MES skin (existing) |
| http://localhost:8000/mes-app/ | React MES app (new) |
| http://localhost:8000/docs | Interactive API docs (Swagger UI) |

## MES API — production jobs (Phase 2B-1, WO v4.14)

New `/api/production-jobs/*` surface (parallel to the legacy `/api/calculations/*`
handlers, which retire in Phase 4). All endpoints require an authenticated session.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/production-jobs` | List jobs (filters: `status`, `branch_id`, `accepted_since`, `limit`, `offset`); items carry `calculation_record_id` for the Costings dashboard join (WO v4.19) |
| GET | `/api/production-jobs/{id}` | Job detail with joined costing data |
| POST | `/api/production-jobs/from-calculation/{calculation_id}` | Accept a costing into production (idempotent: 201 new / 200 existing) |
| POST | `/api/production-jobs/{id}/pre-job-card` | Send pre-job card (422 for repair quotes) |
| POST | `/api/production-jobs/{id}/pre-job-signoff` | Record sales/production sign-off (auto-confirms when both present) |
| POST | `/api/production-jobs/{id}/planning-ack` | Planning acknowledgement (requires `pre_job_confirmed`) |
| POST | `/api/production-jobs/{id}/chassis-received` | Confirm chassis arrival |
| GET | `/api/production-jobs/{id}/timeline` | Derived lifecycle timeline |

The React Costings screens read + write through this surface as of **WO v4.19 (Phase 2C-3)** — the dashboard
joins `/api/calculations` (spine) with this list by `calculation_record_id`, and the accept flow is a sequential
two-call (`/api/calculations/{id}/accept` → `from-calculation/{id}`). With v4.19 **all** MES React contexts
(Costings, Materials, Planning) ride `lib/api` (CSRF + branch-aware + pessimistic refetch). **Phase 2C complete.**

## MES API — materials / buying / stores (Phase 2B-2, WO v4.15)

Surfaces for the Materials, Buying, and Stores screens (ADR 0008/0009). All require
an authenticated session. The catalogue lives in `icb_mes.mes_materials` (migration
`0004`); the MES materials API is at `/api/mes-materials` because the costing admin
already owns `/api/materials`.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/mes-materials` | Catalogue + stock (filters: `dept`, `abc_class`, `low_stock`, `branch_id`) |
| GET | `/api/mes-materials/{sap_code}` | Material detail + current stock + recent (5) counts |
| GET | `/api/stock-counts` | Cycle counts (filters: `status`, `branch_id`, `counted_since`) |
| POST | `/api/stock-counts` | Record a count (auto confirmed/discrepancy) |
| POST | `/api/stock-counts/{id}/raise-discrepancy` | Raise a discrepancy (422 unless count is a discrepancy) |
| GET | `/api/discrepancies` | Buyer queue (filter: `resolved`) |
| POST | `/api/discrepancies/{id}/resolve` | Resolve (422 if already resolved) |
| GET | `/api/po-suggestions` | PO queue (filters: `status`, `urgency`) |
| POST | `/api/po-suggestions/{id}/raise` | Raise PR — mock SAP `PR-{seq}` (422 if already raised) |
| POST | `/api/po-suggestions/{id}/defer` | Defer until a date (422 if already raised) |
| GET | `/api/demand-lines` | Forecast read-model (`group_by=week\|sap` rollup) |
| GET | `/api/suppliers` | Supplier master |

## MES API — planning / session / roles (Phase 2B-3, WO v4.16)

Closes the Phase 2B API layer (ADR 0010). Per-role gating reuses the costing
permission tables via `require_permission`; the active branch is session-held.

| Method | Path | Purpose (permission) |
|--------|------|---------|
| GET | `/api/session` | Current user + active branch (JHB default) + accessible branches + `permissions[]` (WO v4.17) + `csrf_token` (WO v4.18 — lets the SPA send `X-CSRF-Token` on mutations) |
| POST | `/api/session/branch` | Switch the active branch (404 if unknown); drives the TopNav branch picker (WO v4.18) |
| GET | `/api/planning-board` | Board: weeks × slots, unscheduled pool, capacity |
| GET | `/api/planning-slots` | List slots (filters: week / lane / status / branch) |
| POST | `/api/planning-slots` | Schedule — `planning.schedule` (422 chassis-ETA gate, 409 occupied) |
| POST | `/api/planning-slots/{id}/move` | Reschedule — `planning.schedule` |
| DELETE | `/api/planning-slots/{id}` | Unschedule (delete the slot) — `planning.unschedule` |
| POST | `/api/po-suggestions/{id}/override-supplier` | Override supplier — `buying.override_supplier` |
| POST | `/api/po-suggestions/raise` | Bulk raise (1 PR / supplier) — `buying.bulk_raise` |

All v4.14–v4.15 mutations are now permission-gated (15 keys, `{domain}.{action}`;
GET stays ungated). Migration `0005` enforces `branch_id` NOT NULL on the MES
tables, seeds the keys + role grants, and adds the `icb_mes.pr_number_seq` sequence.

## Database & migrations

All schema changes go through **Alembic** (`backend/alembic/`). There is no runtime
`create_all`; the dev scripts run `alembic upgrade head`.

```bat
cd backend
alembic upgrade head          :: apply
alembic downgrade base        :: tear down
alembic revision --autogenerate -m "describe change"
```

## Linux / Mac

`scripts/setup.sh`, `scripts/start.sh`, `scripts/start-dev.sh` mirror the `.bat` files.

## Deployment modes

The same build runs cloud or on-prem; only env vars differ (`DEPLOYMENT_MODE`,
`DATABASE_URL`, `AUTH_PROVIDER`, `FILE_STORE`, `SMTP_URL`, `SAP_*`, `ALLOWED_ORIGINS`).
On-prem Windows-Service packaging (NSSM + IIS) and Docker images arrive in later phases.
