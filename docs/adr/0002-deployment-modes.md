# ADR 0002 — Dual deployment modes via environment variables

- **Status:** Accepted
- **Date:** 2026-06-02
- **Work order:** v4.12 (Phase 1)

## Context
The same product must run in two places: Icecold's on-prem Windows Server
(primary production) and a cloud VM (dev/staging + off-site rep tool). We must
not fork the code per environment.

## Decision
A single commit runs in any mode; behaviour is chosen entirely by environment
variables, centralised in `backend/app/config.py` (pydantic-settings). Key
switches: `DEPLOYMENT_MODE`, `DATABASE_URL`, `AUTH_PROVIDER`, `FILE_STORE`,
`SMTP_URL`, `SAP_*`, `ALLOWED_ORIGINS`. Two variables are **required** and the
app fails fast on boot if either is missing: `DATABASE_URL` and `SESSION_SECRET`.
`.env.example` documents every variable; real secrets never enter git.

## Consequences
- No environment-specific code branches; the same artifact is promoted between
  environments.
- Misconfiguration surfaces immediately at startup, not mid-request.
- On-prem Windows-Service packaging (NSSM) and the IIS reverse proxy are deferred
  to Phase 3; only the configuration seam exists in Phase 1.
- The database is **PostgreSQL only** (one local instance, database `icb`, two
  schemas `icb_costings` + `icb_mes`); the legacy SQLite/MySQL engine paths were
  removed during the import.
