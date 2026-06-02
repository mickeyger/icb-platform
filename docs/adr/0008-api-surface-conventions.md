# ADR 0008 — API surface conventions

- **Status:** Accepted
- **Date:** 2026-06-02
- **Work order:** v4.14 (Phase 2B-1)

## Context
Phase 2B builds the JSON APIs the React app will consume (v4.14 production-jobs,
v4.15 materials, v4.16 planning). They need one consistent shape so the surfaces
compose and the Phase 2C React wiring is predictable. This ADR is the binding
convention from v4.14 onward.

## Decision
- **URL shape:** `/api/{resource-plural}/{id}/{action}` — e.g.
  `POST /api/production-jobs/{id}/pre-job-card`. New surfaces are **parallel** to
  the legacy Jinja `/api/calculations/*` handlers, which stay untouched until
  Phase 4.
- **Pydantic schemas per resource** in `app/schemas/<resource>.py` — explicit
  request + response models (`from_attributes=True`, ISO datetimes, `examples`).
  Responses are a **superset**: canonical columns + UI-friendly derived fields
  (e.g. lowercase `status` AND title-case `mes_status`; flat money fields) so the
  Phase 2C wiring is a near drop-in for the existing mockup shapes.
- **Service layer** in `app/services/<resource>.py` holds the business logic
  (status transitions, validation, completeness rules); routers stay thin and
  only translate typed service exceptions into `HTTPException`. `app/services.py`
  was converted to the `app/services/` package to host this.
- **Cross-schema reads** use an explicit `select().join()` helper (e.g.
  `get_with_costing`) — never an ORM relationship across schemas (ADR 0006).
- **Auth:** every `/api/*` endpoint depends on `require_user` (401 for API
  paths). Per-role gating is deferred to v4.16.
- **OpenAPI:** every resource tags its endpoints; FastAPI `/docs` is the contract.

## Consequences
- v4.15 (materials) and v4.16 (planning) follow this template verbatim.
- Two API paths coexist during the transition — legacy `/api/calculations/*`
  (writes `icb_costings.calculations` columns) and new `/api/production-jobs/*`
  (writes `icb_mes.production_jobs`). They are intentionally independent until the
  legacy path retires in Phase 4.
- `pre_job_confirmed` is treated as an auto-transition (implied by both signoffs),
  not a distinct timeline event — the lifecycle round-trip yields 5 events.
