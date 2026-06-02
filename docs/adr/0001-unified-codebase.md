# ADR 0001 — Unified codebase (single monorepo)

- **Status:** Accepted
- **Date:** 2026-06-02
- **Work order:** v4.12 (Phase 1)

## Context
Icecold Bodies ran two separate codebases: the live Cost Calculator (FastAPI +
Jinja2, at faje.co.za) and the MES mockup (React + Vite, on developer laptops).
They are one product; keeping them apart duplicated effort, data models, auth,
and deployment, and made the MES↔costing integration brittle (cross-port
iframes).

## Decision
Merge both into a single git repository, `icb-platform`:
- `backend/` — the FastAPI app (Cost Calculator today; MES API over time).
- `frontend/` — the React + TypeScript + Vite MES UI.
- `shared/`, `deploy/`, `db/`, `docs/`, `scripts/` — supporting concerns.

Phase 1 imports *copies* of both apps essentially unchanged; the original repos
keep running. One FastAPI service serves both the Jinja pages and the built
React SPA on a single port (8000). A Vite dev server (5173) is used only for
hot-reload work and proxies `/api` + `/mes` back to 8000.

## Consequences
- One build, one test suite, one dependency graph, one deployment artifact.
- Jinja and React coexist during the multi-phase UI migration (Phase 4/5); no
  big-bang rewrite.
- The live Cost Calculator at faje.co.za is untouched in Phase 1 and remains the
  production hot-fix path until cutover (Phase 6).
- Short-term duplication (TypeScript types vs Pydantic models) until type
  generation lands (Phase 2).
