# v4.36e §3.0 — Dispatch Zone re-land: discovery synthesis

**Method (per the §3.0 artifact pattern):** three subagents in parallel — **A** inventory the reverted zone, **B** journey-failure forensics, **C** Cockpit integration — each producing an artifact (below); synthesized + spot-checked by CA1 against the v4.36e worktree (off main `b2b55f2`, which carries the v4.36d Cockpit).

- A → [`v4_36e_S3_0_inventory.md`](v4_36e_S3_0_inventory.md)
- B → [`v4_36e_S3_0_journey_failures.md`](v4_36e_S3_0_journey_failures.md)
- C → [`v4_36e_S3_0_cockpit_integration.md`](v4_36e_S3_0_cockpit_integration.md)

## Headline — frontend-only, single-sourced, and the fix is layout glue

- **Backend already on main** (never reverted): `GET /api/qc/dispatched` → `list_dispatched` (`backend/app/services/qc.py:95`, route `routers/qc.py:39`). The re-land is **frontend-only** — no backend, **no migration, no new dependency**.
- **The dispatch zone lives in the SHARED `BayModelLanes`** — which the **Cockpit also mounts** (`PlanningCockpit.tsx:28` import, `:600` render, in its bottom dock). So re-adding the zone to `BayModelLanes` lights it up on **both the Board and the Cockpit for free** — nothing to duplicate, nothing to extract. (The bay model is already single-sourced; only the week-grid / `badges` / slot-detail / `useMiddleButtonPan` are the v4.36d KEEP-IN-SYNC copies.)
- **The regression was Board-only and purely layout** (B, file:line-pinned): `BayModelLanes` is a non-`shrink-0` sibling (`PlanningBoard.tsx:1143`) of the **only `flex-1` child** (the week grid). A 2nd `col-span-2` row grew it → stole the grid's height → the sticky-header `slot-cell`s reflowed → Playwright's "stable bounding box" gate never passed → "slot-cell not stable" (7 scenarios, 4 files). The async `/api/qc/dispatched` render caused the *second* reflow. The **Cockpit is structurally immune** — its `BayModelLanes` sits in a `shrink-0`, bounded `max-h-[44vh] overflow-auto` dock (`PlanningCockpit.tsx:587-603`), isolated from the `flex-1` body.

## Re-land design (C's verdict, integrating B's constraints)

1. **Re-add the zone in `BayModelLanes.tsx`** (after the Awaiting-QA zone) using the **decoupled, mount-only `useEffect` fetch** (the `e69483d` flavour) — *not* the `292ffb5` `allSettled` shared-refresh (which slowed the focus-refetched floor). Read-only, no mutations.
2. **Fix the Board regression at its source:** wrap `<BayModelLanes/>` at `PlanningBoard.tsx:1143` in a **`shrink-0` + height-bounded (`max-h` + `overflow-auto`)** container — layout glue, *not* the frozen grid chain. This caps `BayModelLanes`'s height, so adding the zone scrolls *within* it instead of stealing the week grid's `flex-1` height → no reflow → the 7 journeys pass **unchanged**. Mirrors the Cockpit dock's proven pattern.
3. **Cockpit: no code change** (structurally immune); optional one-word "· Dispatch" on the dock label (`PlanningCockpit.tsx:594`).
4. **Defer the `_shared/` refactor** — the bay model is already single-sourced; the week-grid/badges duplication is a *separate* follow-up for when the Board is unfrozen. *(Rejected (a) extract-now: solves a non-existent duplication + needs a Board-unfreeze, off-scope; rejected (b) duplicate: creates new KEEP-IN-SYNC debt.)*

**B's C3 ("render outside the flex column") and C's verdict ("keep in `BayModelLanes`, wrap it") are reconciled:** the `shrink-0`/bounded wrapper *is* the height-isolation B asks for, achieved without sacrificing the single-source.

**Trade-off to flag:** capping `BayModelLanes` (step 2) makes the Board's bay-model section a **height-bounded, internally-scrolling region** (like the Cockpit dock) when its content is tall — it gains an internal scrollbar instead of running full-height. It's the known-good Cockpit pattern; the exact `max-h` + the scroll feel are a §3.2 + click-through call. (If you dislike the scroll, alternatives exist — a tabbed Awaiting-QA/Dispatch zone, or a collapsible — at more UX cost.)

## Hard constraints (B) that gate §3.2
**C1** don't add height to the shared `flex h-full flex-col` column · **C2** height-bound + scroll-contain if kept in `BayModelLanes` · **C3** isolate the zone's height impact from `slot-cell` · **C4** reserve height up-front + mount-only fetch (no async reflow) · **C5** don't touch the grid flex chain (`:953/:1018/:1019`) · **C6** verify on CI (ADR 0011). → The step-2 wrapper satisfies C1–C3 + C5; the decoupled mount-fetch satisfies C4.

## Refined phase split (the discovery simplifies the brief's expected split)
- **§3.1 — Playwright trace-upload CI infra** (independent, lands first) + the retention-policy decision. The engagement-infra win: the observability that would have pinned this regression in one CI run instead of a revert.
- **§3.2 — Re-land:** the `BayModelLanes` zone (decoupled fetch) + the `PlanningBoard:1143` bounded wrapper. **Covers both Board + Cockpit.**
- **§3.3 — Cockpit:** collapses to ~nothing (free via the shared `BayModelLanes`; optional label) — folds into §3.2 verification.
- **§3.4 — Journeys:** the existing 7 should pass **unchanged** (the wrapper isolates the height; no surface change). **ADD the dispatch-resilience journey** (the v4.36c §3.6 deferred one: abort `/api/qc/dispatched` → assert the other zones unaffected + the zone's error indicator).
- **§3.5 — LEAKCANARY:** likely **N/A** — the re-land is a read-only GET with a generic client-side "couldn't load" branch; no new server error/log paths. Confirm during §3.2.
- **§3.6 — §3.8 ADR + click-through + close.**

## Constraints honored
- **No migration, no new dependency** (frontend-only; backend + `AwaitingQaRow` type already on main). Hold-and-surface if §3.2 finds otherwise.
- **No cross-lane touch** — only `BayModelLanes.tsx` + `PlanningBoard.tsx` (the Planning lane). No costings / chassis / calculator / admin. CA4 #58 + CA5 #52 unaffected.
