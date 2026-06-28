# v4.36d — Cockpit Promotion (architecture note)

- Status: Accepted (incremental — ratified §3.0 → §3.x at each checkpoint)
- Date: 2026-06-28
- Work Order: v4.36d Cockpit Promotion (Phase-1 prep; ship target Tue 8 Jul 2026)
- Builds on: ADR 0018 (bay model + dashboard unification), ADR 0028 (v4.36c QC + Dispatch), the v4.36b
  visual-integrity system, and the demo-prep "Cockpit" stash.
- Note on location: written to `docs/architecture/` per the §3.1 WO; the earlier ADR-numbering ratification
  assigned v4.36d → **ADR 0029** (the other v4.36 records live at `docs/adr/0025-0028`). Reconcile the
  convention at review (this doc, or `docs/adr/0029-cockpit-promotion.md`).

## Context

v4.36d promotes the **Cockpit** — an ADDITIVE alternate Planning layout (Concept 6) at `/planning/cockpit`
— from an untracked demo-prep stash into a tracked, integrated surface, alongside a cost-breakdown PDF
export fallback. The existing `PlanningBoard.tsx` is **frozen/unchanged**; the Cockpit is a parallel view
over the **same data + the same mutators** (`PlanningContext`), cross-synced via the existing
`icb:planning-refetch` event. Zero migrations, zero DB writes (alembic head stays `0029`).

## Foundation commit composition (`7e12a24`)

The §0.18.5 stash pop = **7 files** (3 modified + 4 new):
- `backend/app/routers/exports.py` (+426) — the WeasyPrint **fallback** (below).
- `frontend/src/App.tsx` — additive `/planning/cockpit` route (`<Layout>`-wrapped, so the v4.38 FeedbackWidget renders).
- `frontend/src/components/layout/TopNav.tsx` — Planning nav → **split-button** (ITEM 1).
- `frontend/src/screens/Planning/cockpit/{PlanningCockpit,CockpitSlotDetail}.tsx` + `useCockpitLayout.ts` + `badges.tsx`.

Transferred via `git apply --3way` (the tracked patch, 3-way-reconciled with #59's TopNav `/admin/qc`
repoint that landed mid-transfer) **plus a manual copy of the 4 UNTRACKED cockpit files** — a plain
`git stash` captures only *tracked* changes, so the cockpit components weren't in the patch (a git-mechanics
gotcha worth recording for future stash transfers).

## The cost-breakdown PDF export is a WeasyPrint FALLBACK (not a new feature, not a "fridge fix")

`_cost_breakdown_pdf_reportlab` (`exports.py:433`) is the **reportlab fallback inside the existing
`export_pdf` route**: the diff replaces a hard `RuntimeError("WeasyPrint is not installed")` with
`except (ImportError, OSError): pdf_bytes = _cost_breakdown_pdf_reportlab(ctx)`. WeasyPrint stays **primary**
— prod has Pango 1.52.1 (installed mid-Jun) so prod uses WeasyPrint; the reportlab path is load-bearing for
**CI + dev + any future env where Pango availability shifts**. It is read-only, RBAC-gated (`export.pdf`),
and injection-safe (all free-text is `escape()`d before entering reportlab `Paragraph` XML). §3.1 also fixed
the route's 500 handler to **log the exception server-side and return a generic client message** (it had
leaked raw `exc` text to the caller).

## ITEM 1 — the Planning-nav split-button (the §3.1 load-bearing fix)

The foundation made `nav-planning` a `<button>` that *opened* a Board/Cockpit menu instead of navigating —
which would break **13 Playwright journeys** (every one clicks `nav-planning` to reach the board) AND regress
**single-click-to-board** for daily users. **Decision: Option (b) — split-button.** The label half is a
`<NavLink to="/planning">` (keeps `data-testid="nav-planning"`, navigates); a separate chevron half
(`data-testid="nav-planning-menu"`) opens the Board/Cockpit menu. Hover/active lift both halves coherently
via the shared wrapper. This preserves all 13 journeys **with zero test edits** + single-click-to-board, and
is **strategy-neutral** whether the dropdown stays or the Cockpit later becomes the default Planning surface.
(Rejected: Option (a) — rewrite 13 journeys + accept the single-click regression.)

## Deferred items (with explicit follow-ups)

- **Forked view code** — the Cockpit's grid/drag handlers, `badges.tsx` (`ChassisBadge`/`SourceBadge`/
  `FooterRow`), `CockpitSlotDetail`, and `useMiddleButtonPan` are **copied** from the frozen `PlanningBoard`
  (its privates aren't exported), carrying "KEEP IN SYNC" comments → a dual-maintenance liability.
  **Follow-up:** promote to `frontend/src/screens/Planning/_shared/` once the Board is un-frozen.
- **Cockpit drag keyboard a11y** — the pool cards are `draggable` `<div>`s with no `onKeyDown` path (no
  keyboard scheduling). Deferred to a post-ship a11y pass — the Board has the *same* gap, so no parity
  regression, and the Phase-1 deadline is binding.
- **Bay-flag discoverability** — the v4.36b bay flags render in the Cockpit's bay dock, collapsed by default
  → less discoverable than on the Board. Deferred to a post-ship UX cycle (default-open the dock, or accept).

## Method

§3.0 discovery = three subagents in parallel (cockpit-vs-board, adversarial, inventory) → synthesis
(`docs/audit/v4_36d_S3_0_*.md`). Two §3.0 corrections shaped this note: the blast radius was **13 journeys**
(not the initial ~7), and the exports.py change is a **WeasyPrint fallback** (not the "fridge fix" the stash
framing implied — its third, code-grounded characterization).

## Consequences

- Two Planning surfaces (Board default, Cockpit beta) over **one** data layer + **one** set of mutators — no
  data split-brain; a *managed* view-code fork (the deferred consolidation).
- No schema/DB change → no reseed. Per ADR 0011 the journeys can't run locally, so the **draft PR's CI is the
  journey verification** — engineered green-on-first-try by keeping `nav-planning` a navigating link.
