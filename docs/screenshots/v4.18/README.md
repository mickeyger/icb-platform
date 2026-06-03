# WO v4.18 — Phase 2C-2 screenshots & live verification evidence

Generate the PNGs with the reusable headless capture step (preview tooling can't
write PNGs to disk):

```bash
cd frontend
npm i -D playwright && npx playwright install chromium
node scripts/capture-v418.mjs          # MES_BASE defaults to http://localhost:8000
```

Point it at a **permitted autologin origin** serving the built SPA against a live
backend — i.e. the FastAPI server at `:8000` serving `/mes-app/` (the dev origins
`:8000/:5173/:4173` are in the autologin allowlist; `:8090` is not).

Expected files: `planning-board-live.png`, `branch-picker-open.png`,
`branch-switch-result.png`.

## Live verification performed (admin session, `http://localhost:8000/mes-app/`)

All of the below was exercised against the live Postgres-backed backend and
captured from the browser network log / DOM during the build.

### Reads — board renders live
- `GET /api/session → 200` (role admin, 15 permissions, active branch JHB, `csrf_token` present, len 64).
- `GET /api/planning-board?weeks=8 → 200` → board renders **2 live weeks** (2026-W22, 2026-W23),
  the unscheduled pool (4 jobs), the capacity footer (W23 filled 1 / value R129k), and the
  scheduled cell `32891 Rustenburg Toyota` in V-1 / W23.
- All six v4.15 Materials reads still `200` (no regression from the bootstrap/refetch refactor).
- No console errors.

### Chassis state badges (§3.3) — validated against live data
| Job | `chassis_eta` | `chassis_received_at` | Badge shown |
|---|---|---|---|
| #32985 Hestony | set (2026-07-20) | null | **"ETA committed"** (amber) ✓ |
| #32850 Spar SA | set | set | none (received) ✓ |
| #32940 / #32970 | null | null | none (case (a)) ✓ |

### Mutations / gate — endpoint behaviour (verified with a valid CSRF token)
- Schedule a received job into an empty cell → **201 Created** (slot persisted, `planned_start_date` set).
- Move that slot to another cell → **200 OK**.
- Unschedule → **200 OK** (job returns to the pool).
- Schedule a job whose chassis ETA is after the target week → **422** with the verbatim
  diagnostic: *"chassis ETA 2026-07-20 is after the target week (ends 2026-06-05); ~45 day(s)
  short — mark chassis received or pick a later week"* (rendered verbatim in the §3.2 case-(b) toast).
- Schedule into an occupied cell → **409** *"slot V-1 in week 2026-W23 is already occupied"*
  (drives the inline cell-reject + amber toast).
- Case (a) (`chassis_eta IS NULL AND chassis_received_at IS NULL`): the v4.16 gate **allows** it
  server-side, so it is blocked **client-side** in `PlanningBoard` (amber toast, no POST) per the
  BA-locked §3.2 decision.

### CSRF enabler (Option A) — SPA mutations unblocked
Before the fix, `POST /api/planning-slots` from the SPA returned **403 "CSRF token missing"**
(the SPA sent no `X-CSRF-Token`). After exposing `csrf_token` on `GET /api/session` and having
`lib/api` send the header:
- **`POST /api/session/branch → 200 OK`** (switch to CPT) — the definitive end-to-end proof that
  SPA mutations now pass CSRF.

### Branch picker (§4.3) + branch-changed signal (§4.4)
- Dropdown lists all three branches: **CEN Central, CPT Cape Town, JHB Johannesburg (current)**.
- Selecting CPT → `POST /api/session/branch → 200` → **`GET /api/planning-board` + all six Materials
  reads re-fire (200)** with **no re-autologin** — the targeted refresh + the §3.5 bootstrap/refetch
  split both confirmed.
- CPT (no seeded data) → board shows the **`EmptyState`** ("No scheduled weeks yet"), pool 0, 0 weeks.

### Loading / build
- Initial load shows the **`Skeleton`** board (the primitive's first real use, §3.1).
- `npm run build` clean (tsc + vite). Backend `pytest tests/test_planning_session_roles_api.py` → 20/20.
