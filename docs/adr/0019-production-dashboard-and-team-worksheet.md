# ADR 0019 — Production Dashboard wire-up, the team-worksheet contract, and the deep-link convention

- **Status:** Accepted
- **Date:** 2026-06-11
- **Work order:** v4.32 (Phase 3 §4.5 — Production Dashboard Wire-Up + Per-Team Daily Worksheet)

## Context

The Production Dashboard was the last Phase-0 mock surface on the main flow: every tile, bay
and panel rendered `data/mockData`. v4.31 had just landed the entities the real version needs
(assembly/parking bays, event-derived assembly state, the reusable job-card component). v4.32
wires the dashboard to real aggregations, adds the per-team daily worksheet, and closes the
v4.29 D7 carry-forward (the disabled "View in Production" button). This ADR records the
load-bearing decisions and the (now six) test-infrastructure patterns the WO surfaced.

## Decision

### 1. The per-team worksheet is ONE uniform contract, not five endpoints

`GET /api/production/team-worksheet?team=&date=&branch_id=` returns the same shape for all
five teams:

```
{ team, date, capacity?: {used, total},
  sections: { scheduled: Item[], in_flight: Item[], blocking: Item[] } }
Item = { job_id?, job_number?, chassis_vin?, customer?, description?,
         location?, status, since?, flag? }
```

Team-specific fields are simply **nullable** — parking rows are chassis-anchored, slot rows
are job-anchored, dispatch rows may be both — so the frontend renders every tab through one
row component. Per-team sources: vacuum/press read `planning_slots` for the week containing
the date (slots are week-granular; **press maps to the v4.16 lane vocabulary `'panelshop'`**,
the UI label notwithstanding); assembly reads the event-derived occupants; parking reads the
booked-in pool (`in_workshop`) + a capacity chip counted from the `parking_bays` master
(informational — the yard has no formal slot allocation until Phase 4); dispatch reads
completed-pending-collection (chassis not yet DCL'd) + collected-on-date. Blocking sections
carry the §0.6 flags (chassis-ETA overdue, awaiting-collection > 7d, open rework matched to
the team by `routed_to_bay` prefix — legacy free-text values that match no team surface only
in the global KPI). The ±7-day date clamp lives in the service (422), mirrored by the date
input's min/max.

### 2. The cross-screen deep-link convention: `?jobId=` → handle → CLEAR

The re-enabled D7 button navigates `/production?jobId=<job_number>`. The dashboard handles
the param **once live data is loaded** and then **always clears it** (`replace: true`):
found → scroll to the bay tile + ~4s highlight ring + auto-open the bay side-panel;
not found (dispatched / dropped / not on a bay) → an amber toast with the §3.5 locked copy.
**Never 404, never silently ignore, never leave the param in the URL** (a stale param would
re-fire on the next refresh tick). This is the convention for future cross-screen navigation:
params are *commands*, consumed exactly once, with explicit feedback on both outcomes.

### 3. Bay drill-down = the v4.31 job card, reused as-is; tablet view deferred

The bay side-panel renders `JobCardSections` (v4.31) unchanged — chassis detail, BOM (with
its honest missing-data placeholders), bay context, workshop price-hide intact. This is the
**pattern compounding**: v4.31 extracted the component for LiveSlotDetail; v4.32 consumes it
on a second surface with zero modification. The per-bay *tablet* drill-down (floor-operator
view) is explicitly out of scope (~v4.36+, pending Simeon's authentic assembly check
sequence).

### 4. Production KPIs: the second parity-by-construction instance

`compute_production_kpis()` (services/production_jobs.py) is a **new** computation in the
production domain — NOT an extension of the costings-domain `compute_kpis()` (wrong
abstraction) — but it follows the same v4.31 rule: one shared function, every consumer calls
it. Today's only consumer is `GET /api/production-jobs/kpis`; the Management Dashboard
(v4.33+) becomes the second caller and inherits parity for free. The §0.6 schema-aligned
defaults shipped: in-flight = job status ∈ {planning, in_production} (chassis statuses are a
separate dimension); delayed = start-slipped ∪ chassis-slipped (no planned-completion column
exists — the original "today > planned completion" was unimplementable); bottleneck = longest
time-in-current-stage (latest populated lifecycle timestamp) when > 2 days; `target_today =
null` (no target seeded → the UI renders no target line). Burt + Simeon refine post-ship in
v4.32.1. The workshop role's worksheet lens (Parking + Dispatch only — chassis custody) is
the same kind of shipped default, queued for the same validation (task #190).

### 5. Honest panels over fake signals (§0.15)

Three mock panels did not survive contact with real data: the rework list (now a real
`open_rework` count + per-team blocking rows; the table existed since v4.13 with no API),
material alerts (replaced by a link-card to Materials → Suggestions — shortage signals stay
owned by the module that computes them), and the labour-efficiency chart (**no labour-booking
data exists anywhere** — removed in favour of an explicit placeholder naming v4.33+ SAP-read
as the prerequisite). The principle: a wired dashboard renders real signals or says plainly
why it can't — it never decorates with illustrative numbers. The same principle removed the
Layout footer's "Phase 0 mockup · Illustrative data" banner (§0.14).

## Test-strategy footnotes (each bit once; pattern-fixed here)

1. **Fixture-leak class + self-healing purge.** A fixture that errors *after* `db.commit()`
   (here: touching `branch.id` on a detached ORM instance once the session closed) never
   reaches its teardown — the committed rows leak and every later test dies on duplicate
   keys. Discipline: **capture primitives in-session**, and make fixtures **self-healing** —
   delete by marker prefix at setup AND teardown (`try/finally`), so a crashed run cleans up
   after itself on the next run.
2. **Route-order trap.** FastAPI matches in declaration order: literal paths
   (`/kpis`, `/in-progress`) MUST be declared before an int-typed catch-all (`/{job_id}`), or
   they 422 as failed int-parses. Pinned by a dedicated test so a future route reshuffle
   fails loudly.
3. **Wrapper components must forward test attributes.** `Card` swallowed `data-testid` (no
   rest-prop spread): the component mounted and fetched (server logs proved it) while
   Playwright saw nothing. Earlier evidence had worked only because it selected plain
   elements. Fix: additive `...rest` spread on the primitive + a full journey re-run.
   **Verify testids by attribute-check in the DOM, not by render-check in the code.**
4. **Marker-distinct seeding: `T432*` (tests) vs `D432*` (demo) vs `J432*` (journeys).**
   Test purges scan their own prefix only, so demo data survives test runs and vice versa.
   Standing convention for any WO that seeds real tables (candidate for Testing Strategy
   v1.2).
5. **List caps by default.** Any render-time list over variable-cardinality data gets a
   max-height + overflow-scroll (the BayModelLanes treatment) — dev-data realities (a
   46-chassis yard) must not be able to balloon the layout on first load.
6. **Attribute-based time proofs.** The 30s auto-refresh is asserted on the `data-refreshed`
   attribute advancing, not on screenshot diffing — machine-checkable and immune to
   render-timing noise.

## Consequences

- The dashboard + worksheet consume only generic, reusable aggregations (`/kpis`,
  `/in-progress`, bays utilisation, team-worksheet) — the Management Dashboard (v4.33+) and
  the Workshop Tablet (v4.36+) build on the same four, not on screen-specific endpoints.
- The v4.31 bay-utilisation extension stayed additive (`BayOut` gained nullable occupant
  fields on the existing `/api/chassis-records/bays/assembly` — no new namespace), so
  `useBayModel` and every v4.31 consumer kept working untouched.
- Deferred, explicitly: KPI-definition refinement + workshop-lens validation (v4.32.1, after
  Burt + Simeon see it running); per-bay tablet drill-down (v4.36+); SAP-fed KPIs + labour
  booking (v4.33+); websocket/floor alerts + worksheet print (v4.34); yard slot allocation
  (Phase 4).
