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
