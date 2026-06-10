# ADR 0018 — Four-entity slot model, assembly attribution, and the dashboard unification patterns

- **Status:** Accepted
- **Date:** 2026-06-10
- **Work order:** v4.31 (Phase 3 §4.6 — Bay Model + Job-Card Modal + Costings Dashboard Unification)

## Context

v4.31 formalises the slot model that everything downstream depends on. Before it, "bays" existed only
as free-form `String(32)` values on `planning_slots` / `work_orders` — no master table, no physical
meaning. The factory floor reality (verified on-floor by Michael, 10 Jun): **5 assembly bays inside**
the factory, **~24 parking bays outside**, plus the existing vacuum (V-1..5) and press (P-1..3)
process slots on the Planning Board. A chassis arrives (VCL book-in), waits in the yard, is pulled
onto an assembly bay, and is dispatched (DCL). Nothing in the schema could say *where a chassis
currently is* between book-in and dispatch.

v4.31 also unified the Costings dashboard (one React component on `/costings` and `/costings/new`)
and lifted the 5 legacy metric tiles into it. This ADR records the load-bearing decisions and the
reusable patterns they set.

## Decision

### 1. Two physical-location master tables; V/P stay strings (§0.12)

`icb_mes.assembly_bays` (seeded AssemblyBay-1..5) and `icb_mes.parking_bays` (seeded
ParkingBay-1..24) are the ONLY new entities. Vacuum/press remain free-text `planning_slots.bay`/
`lane` values — they are *week-scheduling* slots, not physical locations, and promoting them is
Phase-4 territory. The Planning Board's "four-lane split" is therefore UI-only: the week grid gains
Vacuum/Press lane-group labels; Parking/Assembly render as a separate bay-model row beneath it
(they are a "now" axis — current location — not a week axis).

Migration 0016 is additive + inspector-guarded (the 0007/0011/0012/0014 idiom): bay tables + seeds;
`chassis_lifecycle_events.event_type` widened VARCHAR(8)→VARCHAR(24) (`'assembly_assigned'` is 17
chars); nullable FK `assembly_bay_id` on the **event**; the `chassis.assembly_assign` permission
seeded for planner + production (0013 precedent — permissions ship with the event they gate; admin
is a code-level wildcard; **workshop deliberately has no grant** — it receives assignments).

### 2. Assembly state is EVENT-DERIVED — no denormalised bay column (§0.12)

A chassis's current bay is derived from its **latest `assembly_assigned` lifecycle event**;
`chassis_records.status` gains the value `'in_assembly'` (values-in-comments only — no DDL on
`chassis_records`). An earlier draft denormalised `current_assembly_bay_id` onto `chassis_records`;
the BA realignment dropped it, for reasons worth keeping:

- **Single source of truth.** `chassis_lifecycle_events` IS the lifecycle log. A second "current
  bay" column can drift from it — silently, or via sync code that is itself a bug surface.
- **Pattern consistency.** 0007/0011/0012 extend status enums via comment-only changes; the column
  would have been the first deviation.
- **Negligible read cost at 5-bay scale** — "latest event of type X for chassis Y" is one indexed
  query; list reads batch it.
- **Audit-clean** — one answer to "which bay", always.
- **Phase-4 reversible** — dropping reliance on an event is a code change; dropping a populated
  column is destructive.

The design is now structurally enforced: code that tries to set the column fails (`TypeError:
invalid keyword argument`) because the column does not exist — caught live by the §3.2 test fixture.

Occupancy: **one chassis per bay** (Phase-3 manual guard; full yard coordination is Phase 4). The
service derives occupancy from the events log and raises 409 (`cellOccupied` UX pattern: inline
reject + amber toast). Re-assignment UPSERTs the single per-cycle event (unique constraint
`(chassis_record_id, cycle_number, event_type)`); back-to-parking has **no UI affordance** (Phase 4).

### 3. Frontend gating: three mechanisms, used deliberately

This WO sets the precedent for WHICH gating mechanism to use where — do not conflate them:

- **Form-affordance permissions** (e.g. the VCL/DCL capture buttons): backend-only gate. The button
  renders for everyone; the backend 403s on submit; the error toasts. Fine for click-then-submit
  flows.
- **Drag-affordance permissions** (e.g. `chassis.assembly_assign` drop targets): frontend-gate via
  `SERVER_KEYS` so the affordance itself (drag handles, drop hints) is **absent** for unauthorized
  roles — a mid-drag 403 cannot be surfaced cleanly. Before adding a key to `SERVER_KEYS`, verify
  `/api/session` actually returns it (`services/session.py` serialises the user's effective
  permission set) — otherwise live-mode `hasPermission` silently ungates (returns `true` for keys
  not in `SERVER_KEYS`).
- **Role-based render choices** (e.g. workshop's BOM price-column hide in the job-card modal):
  `sessionRole === 'workshop'` at render time — NOT a permission and NOT an auth gate. The data is
  still fetched identically for every role; the component omits the columns. Use this for display
  policy ("this role shouldn't *see* prices") as opposed to capability ("this role can't *do* X").
  Note `hasPermission('materials.view')` would NOT have worked here: it isn't in `SERVER_KEYS`, so
  live mode ungates it for everyone — the silent-failure mode the SERVER_KEYS check exists to catch.

### 4. Dashboard unification mechanism (§0.13) — why it was a 19-line change

`CostingsDashboard` gained an `embedded` prop: full-page on `/costings`, compressed (chrome-only:
smaller title, no New-Costing self-link, distinct root testid) below the untouched calculator iframe
on `/costings/new`. Actions + modals stay live in both contexts (permission-gated, not
display-only). The extraction was prop-plumbing-free because **all data flows through the global
`CostingsContext`** — the component reads `useCostings()`/`useAppData()` and takes no data props, so
mounting it anywhere under the providers just works; layout was absorbed by the app shell's `<main>`
scroll container (the calculator keeps its full-viewport block; the page scrolls to the dashboard).
The lesson for future embeds: components that read context instead of props are embeddable for free.

### 5. KPI tiles — parity by construction (§0.7/§3.4)

The 5 metric tiles (quotes-this-week, total-quoted, accepted value+count, active materials,
approval-rate ×3 periods) were lifted by **extracting `compute_kpis()`** in `routers/dashboard.py`
and making BOTH consumers call it: the legacy Jinja context (`build_dashboard_context`) and the new
read-only `GET /api/dashboard/kpis`. The lifted tiles cannot drift from the legacy page — changing
the numbers forces both consumers to change together. This is the pattern for any future
"lift legacy into React" work: **share the computation, don't compare the outputs.**

Two deliberate details: the Materials tile counts `icb_costings.materials` (`is_active=True`) — the
legacy source — NOT the `icb_sap` master (a different tile entirely; SAP integration is v4.33). And
the endpoint is require-user (matching the legacy *tile* exposure, which renders to any logged-in
user); the stricter perm on the standalone `/api/dashboard/approval-rates` endpoint is untouched.
Tiles refresh on page load only (§0.11 — no polling/websocket; tile-refresh is a v4.34
conversation).

## Consequences

- The slot model downstream WOs build on (v4.32 production wire-up, v4.33 SAP/job-card print, Phase-4
  yard coordination) now has real entities + a defined attribution event, with the events log as the
  single queryable history.
- `event_type` admits new kinds without DDL (VARCHAR(24), app-validated allowlist per ADR 0015).
- Per-role journeys (admin + primary affected role, Testing Strategy v1.1) cover: bay-model
  (admin + workshop view-only), job-card modal (admin + planner + workshop price-hide), unified
  dashboard (admin + sales) — riding the testid scheme laid during the build
  (`bay-model`/`assembly-bay`/`parking-chassis`, `jobcard-*`, `costings-dashboard[-embedded]`,
  `costings-kpis`).
- Deferred, explicitly: parking-bay per-chassis allocation + yard coordination (Phase 4);
  back-to-parking UI (Phase 4); SAP-read + job-card print (v4.33); production dashboard wire-up
  (v4.32); real-time floor alerts (v4.34).
