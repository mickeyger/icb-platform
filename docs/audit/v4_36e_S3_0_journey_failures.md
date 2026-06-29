# v4.36e Dispatch Zone — §3.0 Journey-Failure Forensics (Subagent B)

**Question:** Why did the v4.36c dispatch zone deterministically break ~7 planning Playwright
journeys with **"slot-cell not stable"** click timeouts, and what hard constraints must the §3.2
re-land satisfy so it does not repeat the failure?

**Verdict:** **Layout-shift regression** (not a selector / DOM / route / data-shape change). The
dispatch `Card` added a **second full-width `col-span-2` row** to `BayModelLanes`, which renders as a
non-`shrink-0` sibling inside `LivePlanningBoard`'s **height-bounded `flex h-full flex-col` column**.
Growing `BayModelLanes` squeezed the only `flex-1` child — the week grid — whose inner
`overflow-auto` sticky-header table then continuously re-laid-out, so the `slot-cell` tiles never
reached Playwright's "stable bounding box" actionability gate.

---

## 1. The journeys that locate `slot-cell` (and what they do after)

Exact selector `data-testid="slot-cell"` (week-grid job tiles, rendered at
`frontend/src/screens/Planning/PlanningBoard.tsx:1077`). Four journey files use it directly; all wait
for the cell to be **visible** and then **click** it — both `to_be_visible()` and `click()` enforce
Playwright actionability (the click also requires the element to be **stable**: same bounding box
across two consecutive animation frames). That stability gate is what a reflowing grid fails.

| # | File:line | What it does after locating slot-cell |
|---|-----------|----------------------------------------|
| 1 | `backend/tests/journeys/test_planning_drag_journey.py:56,59` | `wait_for_selector('[data-testid=slot-cell]')`, then `.first.click()` → asserts the slot-detail **"View in Production"** button is visible/enabled (`test_planning_view_in_production_enabled_d7_closed`). |
| 2 | `backend/tests/journeys/test_production_dashboard_journey.py:117,119` | `get_by_test_id('slot-cell').filter(has_text=JOB_NUM).first` → `expect(...).to_be_visible()` → `.click()` → opens slot panel → clicks **view-in-production** to deep-link the dashboard (`test_admin_deep_link_from_planning_board`). |
| 3 | `backend/tests/journeys/test_job_card_modal_journey.py:85,87` | `get_by_test_id('slot-cell').filter(has_text=job_number).first` → `expect(...).to_be_visible()` → `.click()` → asserts the **job-card modal** (`jobcard-bom`) opens. Drives all 3 modal scenarios (admin / planner / workshop) via `_open_modal`. |
| 4 | `backend/tests/journeys/test_unschedule_revert_journey.py:160-162` | `_open_slot()`: `page.locator("[data-testid='slot-cell'][data-job-id='{job_id}']")` → `expect(...).to_be_visible()` → `.click()`. Used by the **UI** scenarios `test_planner_modal_revert_preserves_invariants_and_audits` (line 172) and `test_workshop_role_no_affordance_and_403` (line 291). (The other 6 scenarios in this file hit the API directly and do NOT touch the grid.) |

**Why "~7":** the count is scenarios, not files — `test_job_card_modal_journey` alone has 3
slot-cell scenarios, `test_unschedule_revert_journey` has 2, plus
`test_planning_view_in_production_enabled_d7_closed` and
`test_admin_deep_link_from_planning_board` = **7 slot-cell-clicking scenarios** across the 4 files.
Every one routes through the same `nav-planning → click slot-cell` path, so a single grid-reflow
defect fails them all together — matching the revert message ("broke 7 planning journeys… twice").

> Note: `test_production_dashboard_journey` reaches the board only in scenario #2
> (`test_admin_deep_link_from_planning_board`, via `nav.click()`); its other scenarios `goto`
> `/mes-app/production` directly and are unaffected. The board path is the common failure surface.

---

## 2. What the zone added (revert diff `b49675d` = what was removed)

`git show b49675d` touches **one file**: `frontend/src/screens/Planning/BayModelLanes.tsx`
(2 insertions / 53 deletions — the revert *removed* the zone). The removed zone (re-added cleanly in
`292ffb5`, fetch-decoupled in `e69483d`) was:

```tsx
{/* WO v4.36c §3.5 — DISPATCH zone: full-width, below Awaiting QA ... */}
<Card data-testid="dispatch-zone" className="col-span-2">      // <-- the second full-width row
  ... {dispatched.length} chassis ... maps AwaitingQaRow[] into w-[184px] tiles ...
</Card>
```

It was inserted as a **direct child of the BayModelLanes grid container** at what is now
`BayModelLanes.tsx:387`:

```tsx
return (
  <div className="mt-4 grid grid-cols-[260px_1fr] gap-4" data-testid="bay-model">   // :387 — 2-col grid, NO row sizing
    <Card data-testid="parking-zone" .../>                                          // col 1
    <div className="flex flex-col gap-4"> ...Pre-Assembly + Merge... </div>          // col 2
    <Card data-testid="awaiting-qa-zone" className="col-span-2" .../>               // :645 — EXISTING full-width row
    {/* dispatch-zone col-span-2 was inserted HERE — a SECOND full-width row */}     // <-- added below awaiting-qa
    ... modals ...
  </div>
)
```

Two intermediate attempts that did **not** fix it (proving the cause is layout, not data):
- `292ffb5` (original): dispatch fetched via `useBayModel`'s **shared** `Promise.all` refresh
  (`useBayModel.ts:47`). Revert msg: this "slowed the focus-refetched floor and destabilised the
  week-grid layout."
- `e69483d`: decoupled the fetch into a local mount-only `apiGet('/api/qc/dispatched')` (the version
  visible in the `b49675d` diff). Reverting the `useBayModel` floor refactor + decoupling the fetch
  "did NOT help" → the LAYOUT impact of the extra `col-span-2` row is the root cause.

### How the week grid and `<BayModelLanes/>` are laid out relative to each other

`LivePlanningBoard` (`PlanningBoard.tsx:908-1190`) renders, in order, inside a **single
height-bounded flex column**:

```tsx
<div className="flex h-full flex-col p-4">                       // :909  fixed height (h-full), column
  <div className="mb-4 flex shrink-0 ...">…toolbar…</div>        // :910  shrink-0 (fixed)
  <div className="grid min-h-0 flex-1 grid-cols-[250px_1fr] ...">// :953  flex-1 — ABSORBS leftover height
    <Card .../>                                                  // :955  unscheduled pool
    <Card className="flex min-h-0 flex-col overflow-hidden p-0"> // :1018 week-grid Card
      <div ref={panRef} className="min-h-0 flex-1 overflow-auto">// :1019 the scroll viewport
        <table>… sticky thead … <button data-testid="slot-cell">// :1027 / :1077 sticky-header grid + tiles
  </div>
  <BayModelLanes />                                              // :1143 sibling — NOT shrink-0, no flex basis
  <div className="flex shrink-0 ...">…LastUpdated…</div>         // :1145 shrink-0 (fixed)
  …SidePanel / PlanningAckPanel…
</div>
```

- The week grid lives at `PlanningBoard.tsx:953` inside the **`flex-1` grid row** — it is the **only
  height-flexible child** of the column.
- The grid Card (`:1018`) is `flex min-h-0 flex-col overflow-hidden`; its child (`:1019`) is
  `min-h-0 flex-1 overflow-auto` — the **self-contained scroll panel** (WO v4.29). Its height is
  whatever the parent `flex-1` row grants it.
- `<BayModelLanes/>` (`:1143`) is a **sibling below** the grid row, **in the same column**, with **no
  `shrink-0` and no flex basis** → it takes its full intrinsic content height first; the `flex-1`
  grid row gets the remainder.

The height bound is real (confirmed up the tree):
- `Layout` (`components/layout/Layout.tsx:15,19`): `<div className="flex h-screen flex-col
  overflow-hidden">` → `<main className="flex-1 min-h-0 overflow-y-auto">`. So `<main>` is one
  viewport tall (minus TopNav). `LivePlanningBoard`'s `h-full` (`:909`) resolves against that → the
  board column is a **fixed height**, and overflow is meant to be absorbed by the grid's *inner*
  `overflow-auto`, not by the page.

---

## 3. Failure shape — categorised and pinned

**Category: LAYOUT-SHIFT (content reflow) → Playwright "element is not stable" actionability timeout.**
Not a new selector, not a DOM/testid change, not a route change, not a data-shape change. The
`slot-cell` testid, its DOM position, the route, and the board payload are all **identical** before
and after the zone.

Causal chain, pinned to file:line:

1. The board column is **height-bounded**: `Layout.tsx:15` (`h-screen overflow-hidden`) +
   `Layout.tsx:19` (`<main flex-1 min-h-0 overflow-y-auto>`) + `PlanningBoard.tsx:909`
   (`flex h-full flex-col`). Vertical space is finite and shared.
2. The week grid is the **sole `flex-1`** child: `PlanningBoard.tsx:953` (the grid row) feeding the
   grid Card at `:1018` and its `overflow-auto` viewport at `:1019`.
3. `<BayModelLanes/>` (`PlanningBoard.tsx:1143`) renders in that same column and is **not height-
   capped** (`BayModelLanes.tsx:386-387` root `mt-4 grid grid-cols-[260px_1fr] gap-4`, no row/height
   constraint, not `shrink-0`).
4. The zone added a **second `col-span-2` full-width row** (`BayModelLanes.tsx:387` container; the
   removed `<Card data-testid="dispatch-zone" className="col-span-2">` stacked under the existing
   `awaiting-qa-zone` `col-span-2` at `:648`). This **increases BayModelLanes' intrinsic height**.
5. Taller BayModelLanes → less height left for the `flex-1` grid row → the grid's inner
   `overflow-auto` viewport (`:1019`) shrinks and **re-flows its sticky-header table**
   (`thead` sticky at `:1031`, `slot-cell` buttons at `:1077`). The dispatch list also fetches async
   (`/api/qc/dispatched`) and renders on arrival → a **second** height change → a **second** reflow
   (matching "not stable, twice").
6. Playwright's `.click()` on `slot-cell` requires the element to be **stable** (unchanged bounding
   box across two animation frames). The repeated reflow keeps moving the tile → the stability check
   never passes → **click times out → "slot-cell not stable."**

Corroboration it is layout, not data: decoupling the dispatch fetch (`e69483d`) and reverting the
`useBayModel` floor refactor did **not** help (per `b49675d` message). Only removing the
`col-span-2` row restored green.

---

## 4. Hard constraints for the §3.2 re-land (these gate the re-land)

The re-landed dispatch zone **MUST NOT** change the height the week grid receives, and **MUST NOT**
introduce post-mount height churn in the shared flex column. Concretely:

**C1 — Do not add height to the shared `flex h-full flex-col` column (`PlanningBoard.tsx:909`).**
The single biggest lever. The week grid (`:953/:1018/:1019`) is the only `flex-1`; anything that
grows a non-`flex-1` sibling steals its height and forces a reflow. The dispatch zone must not
enlarge `BayModelLanes`' contribution to that column's intrinsic height.

**C2 — The dispatch zone must be height-bounded and scroll-contained, not free-growing.**
If it stays inside `BayModelLanes`, cap it (e.g. a fixed `max-h-*` with its own `overflow-y-auto`,
mirroring the Parking pool's `max-h-64 overflow-y-auto` at `BayModelLanes.tsx:404`). It must NOT add
an unbounded `col-span-2` row whose height grows with `dispatched.length`. A second full-width
free-height row is exactly what regressed.

**C3 — Preferred: render the zone OUTSIDE the shared flex column entirely.**
The cleanest fix is to not stack it in the height-bounded board column at all — e.g. give the board
its own scroll region for the bay/dispatch lanes that is independent of the week-grid's `flex-1`
allocation, or move the zone below `<main>`'s natural scroll so its height extends a page-scroll
instead of squeezing the grid. If the zone lives in a region the grid's height does not depend on,
its size (and its async load) cannot reflow `slot-cell`.

**C4 — No post-mount layout shift from the async dispatch fetch.**
Even height-bounded, an empty→populated transition that changes the container's height will reflow
the grid once data arrives. Reserve the zone's height up front (fixed/min height, or a skeleton of
the final size) so arrival of `/api/qc/dispatched` data does not change the column's geometry. Keep
the fetch **mount-only / decoupled** from the floor refresh (the `e69483d` direction) so a focus
refetch never re-sizes it — but note decoupling alone is **insufficient** (C1/C2/C3 are the real
fix).

**C5 — Do not alter the week grid's flex chain.** Leave `PlanningBoard.tsx:953` (`flex-1 min-h-0`),
`:1018` (`flex min-h-0 flex-col overflow-hidden`), and `:1019` (`min-h-0 flex-1 overflow-auto`)
exactly as-is. The grid's self-contained-scroll contract (WO v4.29) is load-bearing for slot-cell
stability; the re-land must not "fix" height by touching it.

**C6 — Verify against a trace, not locally.** Per ADR 0011 (and the revert note), these journeys are
deterministic in CI but not reproducible locally for CA1/the BA. The re-land must be proven by a
green CI run on the 7 slot-cell scenarios (ideally with a Playwright trace/screenshot artifact
confirming the grid is stable), per the banked lessons
`feedback-verify-ci-green-each-phase` / `feedback-blind-debug-get-traces`. Do not declare §3.2 done
on "pushed"/"exercising".

**Out of scope / safe:** the backend (`list_dispatched`, `GET /api/qc/dispatched`) is already
shipped + CI-proven and is NOT implicated — the failure is purely the frontend zone's layout impact.

---

### File:line index
- `frontend/src/components/layout/Layout.tsx:15,19` — `h-screen overflow-hidden` shell + `<main flex-1 min-h-0 overflow-y-auto>` (the height bound).
- `frontend/src/screens/Planning/PlanningBoard.tsx:909` — `LivePlanningBoard` root `flex h-full flex-col`.
- `frontend/src/screens/Planning/PlanningBoard.tsx:953` — `grid min-h-0 flex-1` week-grid row (the only `flex-1`).
- `frontend/src/screens/Planning/PlanningBoard.tsx:1018-1019` — week-grid Card + `overflow-auto` scroll viewport.
- `frontend/src/screens/Planning/PlanningBoard.tsx:1031,1077` — sticky `thead` + `slot-cell` button (the tiles that reflow).
- `frontend/src/screens/Planning/PlanningBoard.tsx:1143` — `<BayModelLanes/>` sibling, NOT `shrink-0`.
- `frontend/src/screens/Planning/BayModelLanes.tsx:386-387` — BayModelLanes root grid (no row/height cap).
- `frontend/src/screens/Planning/BayModelLanes.tsx:648` — existing `awaiting-qa-zone` `col-span-2`.
- `frontend/src/screens/Planning/BayModelLanes.tsx:404` — Parking pool's `max-h-64 overflow-y-auto` (the bounded-zone precedent for C2).
- removed dispatch `<Card data-testid="dispatch-zone" className="col-span-2">` — `git show b49675d` (was inserted after `:648`'s zone).
- Journeys: `test_planning_drag_journey.py:56,59`; `test_production_dashboard_journey.py:117,119`; `test_job_card_modal_journey.py:85,87`; `test_unschedule_revert_journey.py:160-162` (used at `:172,:291`).
- `frontend/src/screens/Planning/useBayModel.ts:47` — shared `Promise.all` floor refresh (the `292ffb5` coupling that `e69483d` decoupled).
