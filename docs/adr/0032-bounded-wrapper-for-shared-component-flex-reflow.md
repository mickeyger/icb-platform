# ADR 0032 — Bounded wrapper for a shared component that perturbs a flex sibling (v4.36e Dispatch Zone re-land)

- **Status:** Accepted
- **Date:** 2026-06-29
- **Work Order:** v4.36e — Dispatch Zone re-land (Board + Cockpit), Phase 1.5
- **Builds on:** ADR 0028 (Kenny QC + Dispatch — kept the `/api/qc/dispatched` backend, CI-proven, and **deferred** the Planning-Board dispatch-zone frontend "until the layout is solved"; this ADR lands that deferred frontend) · `docs/architecture/v4_36d_cockpit_promotion.md` (the Cockpit's collapsible bay-model **dock** — already a `shrink-0` + `max-h-[44vh] overflow-auto` bounded region; this ADR aligns the Board with that precedent) · ADR 0011 (CI / `icb_test` journey execution — journeys are deterministic-in-CI, unreproducible on-box, which shapes both the verification and the §3.1 trace infra).
- **ADR numbering:** 0032 = v4.36e, the latest Phase 1.5 piece (after 0028 v4.36c · *0029 — reserved for v4.36d by ship-order, but v4.36d's decision shipped as `docs/architecture/v4_36d_cockpit_promotion.md`, so ADR 0029 is an **unused gap**; docs/architecture was the placement outlier, corrected back to docs/adr here* · 0030 v4.36.5 · 0031 v4.37).

## Context

WO v4.36c §3.5 added a Dispatch zone (read-only `dispatched`-chassis tiles, fed by `GET /api/qc/dispatched` → `list_dispatched`) to the Planning Board. It rendered as a second full-width `col-span-2` Card inside the **shared** `BayModelLanes` component, directly below the existing Awaiting-QA zone. It **deterministically broke 7 planning journeys** ("week-grid slot-cell not stable" — the `slot-cell` click timing out) and was reverted (commit `b49675d`); ADR 0028 kept the backend and deferred the frontend.

The §3.0 re-land discovery (3 parallel subagents → `docs/audit/v4_36e_S3_0_*.md`) pinned the mechanism (Subagent B): on the Board, `<BayModelLanes/>` (`PlanningBoard.tsx:1143`) is a **non-`shrink-0` sibling** of the week grid — the *only* `flex-1` child — inside a height-bounded `flex h-full flex-col` column (`Layout.tsx` `h-screen overflow-hidden` → `<main flex-1 min-h-0 overflow-y-auto>`). A second full-width zone grows `BayModelLanes`, stealing height from the `flex-1` grid; its sticky-header table reflows and the `slot-cell` tiles never settle to a stable bounding box, so the Playwright click never fires. Pure **layout shift** — not a selector, route, DOM, or data-path change (reverting the `useBayModel` floor refactor + decoupling the fetch did not help; only removing the `col-span-2` row restored green).

Independently, the §3.1 Playwright **trace-upload CI infra** (added so a CI-only journey regression is diagnosable from captured DOM + network + screenshots — the artifact the v4.36c revert lacked) caught the **same mechanism manifesting as a latent flake**: `test_production_dashboard::test_admin_deep_link_from_planning_board` failed on the ubuntu runner with the identical "slot-cell not stable" reflow (15s of the element oscillating stable/unstable) — with the dispatch zone *absent*. So the week grid was already latently reflow-prone whenever `BayModelLanes`' height shifted (its async data load), surfacing intermittently on a slower runner.

## Decision

**Re-land the dispatch zone unchanged in the shared `BayModelLanes`, and fix the regression in the parent layout — not in the shared component — with a bounded wrapper.**

- **The fix lives at the consumer's layout site** (`PlanningBoard.tsx:1143`): wrap `<BayModelLanes/>` in a `shrink-0` + height-capped + scroll-contained container — `<div data-testid="bay-model-wrap" className="shrink-0 max-h-[44vh] overflow-y-auto">`. This caps the bay-model section's contribution to the flex column, so any growth inside `BayModelLanes` (the new zone, or its async re-renders) scrolls *internally* instead of stealing the `flex-1` week grid's height. The grid's height becomes independent of `BayModelLanes`' content.
- **The shared `BayModelLanes` is not special-cased.** The zone is re-added as the same `col-span-2` Card (after Awaiting-QA), fed by a **decoupled, mount-only** `useEffect` fetch of `/api/qc/dispatched` (not folded into `useBayModel`'s focus-refetched floor — a dispatch-feed hiccup can't blank the core zones). Because the Cockpit mounts the same `BayModelLanes` (`PlanningCockpit.tsx`), the zone lights up on **both surfaces** from one change.
- **`max-h-[44vh]`** matches the Cockpit dock's existing value, so the two surfaces behave identically; the value is a layout tuning knob, not a structural commitment.

**General pattern (the reusable decision):** when a *shared* component can perturb a *flex sibling* by changing height, the fix belongs in the **parent layout that composes them** — bound/isolate the shared component there — not in the shared component, which must stay agnostic of every consumer's surrounding layout.

## Consequences

- **Board:** the bay-model section becomes an internally-scrolling, height-bounded region (gains a scrollbar once its content exceeds ~44vh). This is the visual trade-off; it is the known-good pattern proven by the Cockpit dock, and the BA click-through (`:8004`) judged it non-disruptive — measured `clientHeight ≈ 400.8px` (44% of an 911px viewport), `scrollHeight 805 > clientHeight 401` (the bound engaged, content scrolls internally), verdict *"view the planner and merge areas a bit better."*
- **Cockpit:** unchanged — its bay-model dock was already a `shrink-0` + `max-h-[44vh] overflow-auto` region (structurally immune). This ADR **aligns the Board with the Cockpit precedent** rather than inventing a new pattern. The dock's zone-list label gained "· Dispatch" (the only Cockpit edit).
- **Reusability:** the shared `BayModelLanes` can now grow (future zones, taller content) without perturbing siblings on either surface, because each consumer bounds it at its own layout site.
- **Latent flake hardened:** removing the reflow path is expected to clear the pre-existing `test_production_dashboard` ubuntu flake — borne out by 4 consecutive green post-fix CI runs of that journey (see Validation).

## Validation — the triple-confirmation

The same root cause was identified, caught, and fixed by three independent paths:

1. **§3.0 Subagent B** identified the mechanism by code analysis — the `BayModelLanes` ↔ `flex-1` week-grid flex coupling at `PlanningBoard.tsx:1143`.
2. **§3.1 trace infra** caught the same mechanism *empirically* as a latent flake (the `production_dashboard` "slot-cell not stable" reflow on ubuntu, dispatch zone absent) — an independent signal that the coupling was real and pre-existing, not unique to the dispatch zone.
3. **§3.2 fix** removes the reflow path; **§3.4 journey** (`test_dispatch_zone_journey.py`) locks the invariant at the test level — zone renders → `bay-model-wrap` height-bounded + keeps its `max-h` → slot-cell does not move as the zone loads/grows → scrolling the bay model does not move the grid; and `test_production_dashboard` is **green across 4 distinct post-fix CI runs** (the §3.2 gate + 2 reruns + the §3.4 run), foreclosing a "lucky three" reading. The structural explanation makes the evidence causal, not coincidental.

CI is the verification authority (ADR 0011): the §3.4 run is **green on both runners — 129 journeys passed, 0 failed, 0 skipped** — and runs on the **main-integrated** branch (CA5 v4.37 #52 + CA4 v4.36.5 #58 merged in), so it also confirms v4.36e composes cleanly with current main. New-journey close-pattern (worth keeping): explicitly confirm the new journey *ran* (logged a passing `.`) **and** the summary shows `0 skipped` — a silently-skipped new journey reports green at the summary level identically to a real pass.

## Alternatives considered

- **Extract the week grid to `screens/Planning/_shared/`** so Board + Cockpit share one grid implementation (removing the v4.36d KEEP-IN-SYNC fork). **Deferred** — the Board's week grid is the frozen original the Cockpit forked; un-freezing + extracting is a larger refactor than this re-land warrants, and the bay model (the part this ADR touches) is *already* single-sourced.
- **Tabbed Awaiting-QA / Dispatch zone** (one slot, two tabs). Rejected: a click-to-switch cost for no benefit over a bounded scroll, which is non-disruptive and shows both zones at once.
- **Collapsible bay-model section** (the Cockpit dock's toggle, applied to the Board). Rejected: adds an interaction cost (expand to see the floor); the bounded scroll needs no action and keeps the floor always visible.
- **Fix inside `BayModelLanes`** (self-bounding). Rejected: a shared component must not encode any single consumer's layout assumptions; the Cockpit already bounds it externally, so the Board should too (consistency + separation of concerns).

## Deferred

- **Week-grid `_shared/` extraction** (post-Board-unfreeze) — the v4.36d KEEP-IN-SYNC fork remains.
- **§3.1 trace-artifact retention tuning** — 14 days now (cost vs debug value); revisit only if Actions storage cost matters.

## LEAKCANARY

**N/A.** The dispatch zone is a read-only `GET /api/qc/dispatched`; the re-land adds no new server error/log path (the only new error branch is a client-side "couldn't load" indicator). Verified §3.5 — no error-handler change to canary-test.

## References

- **§3.0 discovery artifacts:** `docs/audit/v4_36e_S3_0_{inventory,journey_failures,cockpit_integration,dispatch_zone_discovery}.md`
- **Commits:** `db8a2d3` (§3.0 discovery) · `226848c` (§3.1 trace infra) · `a916cf2` (§3.2 re-land + bounded wrapper) · `0ed285e` (§3.4 resilience journey + `bay-model-wrap` testid)
- **PR:** #61 (`feat/v4.36e-dispatch-zone`)
- **Related:** ADR 0028 (Kenny QC + Dispatch — originating decision, deferred this frontend) · `docs/architecture/v4_36d_cockpit_promotion.md` (Cockpit dock — the bounded-region precedent; *not* ADR 0029, which is a reserved-unused gap) · ADR 0030 (chassis sole-editor, v4.36.5) · ADR 0031 (native cost calc, v4.37) — Phase 1.5 sprint family · ADR 0011 (CI / `icb_test` journey execution).
