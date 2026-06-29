# v4.36e §3.0 — Dispatch Zone × Cockpit Integration (Subagent C)

**Scope:** Where does a read-only "dispatch zone" (QC-passed chassis, fed by `/api/qc/dispatched`)
surface in the v4.36d Planning Cockpit, and how should the Board + Cockpit re-land share it —
extract to `_shared/` now, duplicate (KEEP-IN-SYNC), or defer-and-duplicate?

**Worktree:** `C:/Users/micge/Documents/icb-platform-v4.36e` · branch `feat/v4.36e-dispatch-zone`
(`b2b55f2` v4.36d Cockpit Promotion #60).

---

## 1. The headline finding: the Cockpit mounts the SHARED `<BayModelLanes/>`

The Cockpit does **not** carry its own copy of the bay model. It imports and renders the same
standalone `BayModelLanes` component the Board uses:

- Import: `PlanningCockpit.tsx:28` — `import { BayModelLanes } from '../BayModelLanes'`
- Render: `PlanningCockpit.tsx:600` — `<BayModelLanes />`, inside the collapsible bottom dock
  (`PlanningCockpit.tsx:587-603`), lazily mounted only when `dockOpen` is true (`:598`).

The header comment is explicit (`PlanningCockpit.tsx:1-9`): the Cockpit "reuses … the standalone
**BayModelLanes** / JobCardSections / PlanningAckPanel components." What IS copied from the frozen
Board is only the **week-grid + Unscheduled-pool logic**, `badges.tsx`, `CockpitSlotDetail.tsx`, and
`useMiddleButtonPan` (`PlanningCockpit.tsx:7-9, 36`, `badges.tsx:1-2`, `CockpitSlotDetail.tsx:1-4`) —
NOT the bay zones.

**Consequence (the decisive fact for this discovery):** the dispatch zone was a `col-span-2` Card
*inside* `BayModelLanes` (`BayModelLanes.tsx` outer grid `grid-cols-[260px_1fr]` at `:387`; Awaiting-QA
zone `col-span-2` at `:645-691`; Dispatch zone sat immediately after it). Because both surfaces render
the *same* `BayModelLanes`, **re-adding the dispatch zone to `BayModelLanes.tsx` lights it up on the
Board AND the Cockpit for free** — no Cockpit-specific code, no `_shared/` extraction. There is nothing
to duplicate: the bay model is already single-sourced.

### Cockpit layout map (for the record)

`PlanningCockpit.tsx` `LiveCockpit` (`:120`) — root `div.flex.h-full.flex-col` (`:271`):
- **Toolbar** `shrink-0` (`:273-336`) — source filter, week nav, layout controls (collapse rail / max
  hero / fullscreen).
- **3-pane body** `grid min-h-0 flex-1` (`:339`), columns driven by `gridTemplateColumns` (`:268`):
  - LEFT — collapsible **Unscheduled rail** (pool + Awaiting-Planning-ack cards) (`:341-411`).
  - CENTRE — **hero timeline** (the duplicated week grid) in a `flex min-h-0 flex-col overflow-hidden`
    Card with one inner `overflow-auto` scroll panel (`:414-530`).
  - RIGHT — persistent **inspector** (`CockpitSlotDetail`), replaces the Board's slot pop-up (`:532-583`).
- **Bottom dock** `shrink-0` (`:587-603`) — collapsible (`dockOpen`), labelled
  "Parking · Pre-Assembly · Merge · Awaiting QA"; body `max-h-[44vh] overflow-auto` wrapping
  `<BayModelLanes/>`.
- **Footer** `shrink-0` (`:606-611`) + `PlanningAckPanel` modal (`:614-622`).

**Where the dispatch zone surfaces in the Cockpit:** it appears automatically as the next full-width
zone *inside the dock*, directly under Awaiting-QA — exactly matching the workflow order
PARKING → ASSEMBLY → AWAITING QA → DISPATCH the dock label already advertises. No new rail, no new
panel, no Cockpit edit required. (Minor polish only: the dock's summary label `:594` would ideally gain
"· Dispatch" — a one-word string change.)

---

## 2. The Board's dispatch zone, reconstructed from history

Revert commit **`b49675d`** ("v4.36c §3.5 — REVERT the dispatch zone to green") removed it; the
pre-revert JSX (added in `292ffb5`) is fully recoverable. The zone:

```tsx
{/* DISPATCH zone: full-width, below Awaiting QA. QC-passed chassis released for collection.
    Read-only in MVP (no drag-back — the rework loop is Phase 2+). */}
<Card data-testid="dispatch-zone" className="col-span-2">
  <div className="mb-2 flex items-center justify-between">
    <span className="…uppercase…text-muted">Dispatch</span>
    <span className="text-[11px] text-muted">{dispatched.length} chassis</span>
  </div>
  {dispatchError ? ( …data-testid="dispatch-zone-error"… )
   : dispatched.length > 0 ? (
     <div className="flex flex-wrap gap-2">
       {dispatched.map((c) => (
         <div data-testid="dispatch-chassis" data-id={c.chassis_id}
              className="w-[184px] …border-l-status-green bg-status-green/5 p-2">
           …vin · DISPATCH pill · customer_name · make/model · job_number…
         </div>
       ))}
     </div>
   ) : ( …"No chassis dispatched yet."… )}
</Card>
```

It mirrors the Awaiting-QA zone's visual language (green instead of sky; same `w-[184px]` card,
`flex flex-wrap gap-2`). Read-only — no drop handlers (the rework loop is Phase 2+).

**Backend is already shipped and CI-proven** (it was never reverted): `backend/app/routers/qc.py:39-42`
exposes `GET /api/qc/dispatched` → `_qc.list_dispatched(db)` (live chassis in status `dispatched`).
The `AwaitingQaRow` type the zone consumes still exists (`frontend/src/screens/Chassis/types.ts:45`).
So the re-land is **frontend-only**.

### Two data-path flavours existed (pick one for the re-land)

- `292ffb5` plumbed `dispatched` + a per-zone `errors` object through `useBayModel` via
  `Promise.allSettled` (`useBayModel.ts` at that sha, `:19-20, 55-85, 181`). This **slowed the
  focus-refetched floor** and was implicated in the reflow.
- `b49675d`'s diff shows a later, **more-isolated** approach already in the reverted code: the zone
  fetched `/api/qc/dispatched` in its **own mount-only `useEffect`** (no focus refetch, no shared
  refresh), so a dispatch hiccup could never blank the floor. This is the better starting point.

**Neither data path fixed the regression** — `b49675d` states reverting the `allSettled` refactor and
decoupling the fetch "did NOT help (proving it's the zone's **LAYOUT** impact, not the data path)."

---

## 3. The regression mechanism — and why the Cockpit is structurally immune

**Board (regressed):** `<BayModelLanes/>` (`PlanningBoard.tsx:1143`) is a **sibling** of the week-grid
grid `div.grid.min-h-0.flex-1.grid-cols-[250px_1fr]` (`:953`), both direct children of PlanningBoard's
flex column. The week grid lives in a `flex min-h-0 flex-col overflow-hidden` Card whose inner panel is
`min-h-0 flex-1 overflow-auto` (`:1018-1019`). Adding a SECOND full-width zone (dispatch on top of
awaiting-qa) grows `BayModelLanes` tall enough to **squeeze the `flex-1` week grid**; its sticky-header
table reflows and Playwright's slot-cells "never settle" — the documented break (7 planning journeys,
twice). Per `b49675d`, this is a pure layout interaction, verified by the data-path reverts not helping.

**Cockpit (immune by construction):** `<BayModelLanes/>` (`PlanningCockpit.tsx:600`) is NOT a sibling
of the timeline. It sits in the **separate `shrink-0` bottom dock** (`:587-603`) wrapped in a
`max-h-[44vh] overflow-auto` scroll boundary (`:599`); the week grid is in the `flex-1` 3-pane body
ABOVE it (`:339`). Three independent insulators the Board lacks:
1. The dock is **`shrink-0`** → it cannot steal height from the `flex-1` body; a taller `BayModelLanes`
   is absorbed by the dock's own `max-h-[44vh] overflow-auto`, not by squeezing the grid.
2. The dock is **collapsed by default** and **lazily mounts** `BayModelLanes` only when `dockOpen`
   (`:598`) → in the default state the dispatch zone isn't even in the DOM near the grid.
3. The timeline already has its **own** `overflow-hidden` Card + inner `overflow-auto` (`:414-415`),
   independent of the dock.

**Verdict on §4 risk:** adding the dispatch zone to the Cockpit carries **no meaningful reflow risk**;
the Cockpit's `shrink-0`/`max-h`/lazy-mount dock is exactly the kind of layout fix the Board still
needs. The regression is a **Board-only** problem. Note: the regression manifests through
`BayModelLanes` growth, but the *fault* is the Board's sibling-flex layout, not `BayModelLanes` itself.

---

## 4. VERDICT — duplicate? extract `_shared/`? or defer?

**Recommendation: (c) DEFER the `_shared/` refactor; re-land the dispatch zone directly in the shared
`BayModelLanes.tsx`, and solve the Board's flex regression there.** There is no duplication to incur
and no extraction to justify.

### Why not (a) extract `_shared/` now

The standing v4.36d follow-up is to promote the **week-grid / drag / `badges.tsx` / slot-detail /
`useMiddleButtonPan`** copies — the parts genuinely duplicated between the frozen Board and the Cockpit.
The **dispatch zone is none of those**: it lives in `BayModelLanes`, which is *already* shared. Creating
`_shared/DispatchZone.tsx` would extract a component that has exactly one consumer (`BayModelLanes`) and
solve a duplication problem that does not exist. The real KEEP-IN-SYNC debt is in the week-grid copy,
and touching that requires **unfreezing the Board** — which it is not (the Board is still demo-frozen
per `PlanningCockpit.tsx:8-9` and `CockpitSlotDetail.tsx:4`, both reaffirmed under v4.36d). Off-scope
for a dispatch re-land and against the ~21-28 Jul Phase-1.5 timeline.

### Why not (b) "duplicate in both"

There is nothing to duplicate. Pasting the zone into both the Board and the Cockpit would be strictly
worse than today — it would *create* a new KEEP-IN-SYNC liability where the shared `BayModelLanes`
currently gives single-sourcing for free.

### What to actually do (frontend-only, scoped, Board-risk-contained)

1. **Re-add the dispatch zone to `BayModelLanes.tsx`** (restore `292ffb5`'s JSX), using the
   **mount-only isolated `useEffect`** fetch flavour from `b49675d` (own `useState` for `dispatched` +
   `dispatchError`, no focus refetch, no shared refresh) — not the `allSettled` shared-refresh path.
   Backend (`/api/qc/dispatched`, `list_dispatched`) and `AwaitingQaRow` are already in place.
2. **Fix the Board's layout regression at its source** — the unbounded vertical growth of the
   `BayModelLanes` sibling against the `flex-1` week grid (`PlanningBoard.tsx:953` vs `:1143`). Give the
   Board's `BayModelLanes` region the same insulation the Cockpit dock already has — e.g. wrap the
   `<BayModelLanes/>` at `PlanningBoard.tsx:1143` in a `shrink-0` container with a bounded
   `max-h-[…] overflow-auto`, so a second zone can't squeeze the grid. **Do this in the Board render
   wrapper, not inside the frozen week-grid code** (the wrapper at `:1143` is layout glue, the frozen
   surface is the grid table at `:1016-1140`).
3. **The Cockpit needs zero code changes** — it inherits the zone via the shared component. Optional
   one-string polish: append "· Dispatch" to the dock summary label (`PlanningCockpit.tsx:594`).
4. **Verify against a trace, not locally** — the regression is deterministic in CI but unreproducible
   on the BA/CA1 boxes (ADR 0011). Per the banked lesson, re-land behind a CI run and read the
   planning-journey artifact (slot-cell stability) before ratifying; if it breaks again, get the trace
   rather than guess-and-check. Update `test_planning_drag_journey.py` / `test_bay_model_journey.py`
   in the SAME phase if a `dispatch-zone` assertion is added.

### Trade-off summary

| Option | Dual-maint. debt | Board risk | Fits 21-28 Jul | Verdict |
|---|---|---|---|---|
| (a) `_shared/` now | removes a debt that ISN'T here | **high** (must unfreeze Board grid) | no | reject |
| (b) duplicate both | **creates** new KEEP-IN-SYNC debt | medium | yes | reject |
| (c) re-land in shared `BayModelLanes` + fix Board wrapper layout | none (stays single-sourced) | **low** (touch layout glue at `:1143`, not the frozen grid) | yes | **adopt** |

The `_shared/` promotion of the week-grid/`badges`/slot-detail copies remains a valid, separate
follow-up for whenever the Board is unfrozen — but it is orthogonal to the dispatch zone and should not
gate it.

---

## Evidence index (file:line)

- Cockpit mounts shared `BayModelLanes`: `frontend/src/screens/Planning/cockpit/PlanningCockpit.tsx:28, 600`
- Cockpit dock isolation: `PlanningCockpit.tsx:271` (root flex-col), `:339` (flex-1 body),
  `:587-603` (shrink-0 dock), `:598` (lazy mount), `:599` (`max-h-[44vh] overflow-auto`), `:594` (label)
- Copied parts (NOT the bay model): `PlanningCockpit.tsx:7-9, 36`; `badges.tsx:1-2`;
  `CockpitSlotDetail.tsx:1-4`
- `BayModelLanes` outer grid + zones: `frontend/src/screens/Planning/BayModelLanes.tsx:387`
  (`grid-cols-[260px_1fr]`), `:645-691` (Awaiting-QA `col-span-2`)
- Board regression site: `frontend/src/screens/Planning/PlanningBoard.tsx:953` (flex-1 grid),
  `:1018-1019` (week-grid scroll Card), `:1143` (`<BayModelLanes/>` sibling)
- Reverted dispatch zone: `git show b49675d` (root-cause writeup + the removed JSX);
  added in `git show 292ffb5` (incl. `allSettled` data path in `useBayModel.ts`)
- Backend (shipped, CI-proven): `backend/app/routers/qc.py:39-42` (`GET /api/qc/dispatched` →
  `list_dispatched`); type `frontend/src/screens/Chassis/types.ts:45` (`AwaitingQaRow`)
