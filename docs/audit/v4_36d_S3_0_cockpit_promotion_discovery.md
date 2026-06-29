# v4.36d §3.0 — Cockpit Promotion: discovery synthesis

**Method (per the §3.0 artifact pattern):** three subagents run in parallel — **A** Cockpit-vs-Board comparison, **B** adversarial review, **C** inventory + premise check — each producing an artifact (linked below); synthesized + spot-checked by CA1 against the v4.36d worktree (foundation commit `7e12a24`, branch `feat/v4.36d-cockpit-promotion`). A *mini*-discovery: the demo-prep stash is most of the work, so scope was integration/risk, not green-field design.

- A → [`v4_36d_S3_0_cockpit_vs_board.md`](v4_36d_S3_0_cockpit_vs_board.md)
- B → [`v4_36d_S3_0_adversarial.md`](v4_36d_S3_0_adversarial.md)
- C → [`v4_36d_S3_0_inventory.md`](v4_36d_S3_0_inventory.md)

## Headline

The foundation is **complete, additive, and low-risk**: 7 files, **zero migrations, zero DB writes** (head stays `0029`, single linear chain). The Cockpit is a **functional near-superset of the LIVE planning board** — same data + same mutators (`PlanningContext`/`usePlanning`), same grid / drag-to-schedule / move / unschedule / KPI footer / source filter, **plus** cockpit-only collapsible rails, Max-hero, native-fullscreen Focus, inspector Pin, and dock-auto-open on panel-drag. No lost planning power; the deltas are layout/UX. The legacy **mock** board keeps a few demo-only extras (offline mode, material-risk, repair-WO, guided tooltips, Add-Job stub). `PlanningBoard.tsx` is genuinely untouched.

## §3.0 ITEM 1 — the Planning-nav dropdown (the one decision that gates §3.1)

The foundation turned `nav-planning` into a `<button onClick={toggle}>` that **opens** a Board/Cockpit menu instead of navigating (`TopNav.tsx:212`). Adversarial review put the blast radius at **13 journeys** (not the ~7 first estimated) — all click `nav-planning` to reach the board and would time out.

**Recommendation: Option (b) — split-button.** The navigating half keeps `data-testid="nav-planning"` and navigates to `/planning`; a chevron opens the Board/Cockpit menu.
- **(b):** 0 journey edits, **preserves single-click-to-board** (the highest-traffic nav path the pure dropdown regresses), strategy-neutral if the Cockpit later becomes the default Planning surface.
- **(a)** (update 13 journeys to click `nav-planning` → the "Board" item): 13 edits + a daily-driver UX regression.
- **Do NOT ship the current pure-dropdown** — it's a 13-journey CI break + a daily UX regression.

## exports.py +426 — recharacterized (premise correction, for the §3.8 ADR)

`_cost_breakdown_pdf_reportlab` is the **WeasyPrint FALLBACK** inside the existing `export_pdf` route (`exports.py:777`): the diff **replaces a hard `RuntimeError("WeasyPrint is not installed")`** with `except (ImportError, OSError): pdf_bytes = _cost_breakdown_pdf_reportlab(ctx)`. So it **coexists** (WeasyPrint primary, reportlab fallback), is **read-only**, and is **RBAC-gated** (`user_can(user, "export.pdf")`, `exports.py:779`). It is not a "fridge fix" — it's *"make the cost-breakdown PDF export work where WeasyPrint isn't installed"* (likely the prod env). Security: all free-text is `escape()`d → **no injection vector**; one **should-fix** — the 500 handler echoes raw `exc` to the client (`exports.py:858`, internal-error leak).

## Risk register

| # | Risk | Severity | Disposition |
|---|---|---|---|
| 1 | nav-dropdown breaks 13 journeys + regresses single-click-to-board | **must-fix** | §3.1 — Option (b) split-button |
| 2 | exports.py 500 handler echoes raw `exc` (info leak) | should-fix | §3.1 (~5 lines) |
| 3 | Cockpit drag has zero keyboard a11y (`draggable` divs, no `onKeyDown`) | should-fix | §3.x or post-ship a11y pass |
| 4 | Forked view code — grid/drag/`badges.tsx`/`CockpitSlotDetail`/`useMiddleButtonPan` **copied** from the frozen Board ("KEEP IN SYNC") | moderate (dual-maintenance) | promote to `_shared` after Board un-freeze; **not a §3.0 blocker** |
| 5 | v4.36b bay flags less discoverable in Cockpit (dock collapsed by default) | minor | UX call — default-open the dock, or accept |
| 6 | Inspector can't collapse while a job is selected; `todayIso()` local-TZ drift | nice-to-have | post-ship |

**Cleared (not defects):** silent-deferral sweep — every cockpit mutator self-surfaces via `handleApiError` + toast at the context layer (the terse local 409-only catches are safe); PDF empty/zero-row states are all `if`-guarded; the QC inbox (`/admin/qc`) and the v4.38 FeedbackWidget coexist cleanly (Cockpit is `<Layout>`-wrapped). Rule-18: `useCockpitLayout` is clean (layout-state only, no data-hook duplication).

## Proposed §3.1 scope
1. **ITEM 1 split-button nav** (Option b) — the load-bearing fix (unblocks 13 journeys + preserves single-click).
2. **exports.py 500-handler leak** (should-fix, ~5 lines).
3. *(optional)* cockpit drag keyboard a11y — or defer to a post-ship a11y pass.

Then open the draft PR → **first CI green-on-first-try** (per the verify plan).

## No reseed
§3.0 touched no shared DB (pure-read UI + a read-only PDF fallback). No snapshot/reseed needed (verify-cycle-close N/A).
