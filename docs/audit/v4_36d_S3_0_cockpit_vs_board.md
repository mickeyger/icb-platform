# v4.36d §3.0 — Planning Cockpit vs Planning Board (mini-discovery, Subagent A)

**Scope.** Cockpit-vs-Board feature comparison, integration with the v4.36c QC inbox,
v4.36b visual-integrity flags, and the v4.38 FeedbackWidget, plus an alembic pre-check.
All paths are in the v4.36d worktree (`feat/v4.36d-cockpit-promotion`, foundation commit
`7e12a24`).

**The Cockpit.** `frontend/src/screens/Planning/cockpit/PlanningCockpit.tsx` — an additive
alternate Planning layout at `/planning/cockpit` (Concept 6): a 3-pane shell (collapsible
Unscheduled rail · hero week-grid timeline · persistent right-hand inspector) with a
collapsible bottom dock for the bay-model zones and a native-fullscreen Focus mode. It
reuses the **same live data + mutators** as the Board (`usePlanning`, `useCostings`) and the
same standalone components (`BayModelLanes`, `JobCardSections`, `PlanningAckPanel`). The
grid/pool/badge logic is **copy-forked** from `PlanningBoard.tsx`'s module-private
`LivePlanningBoard` into cockpit-local files (`badges.tsx`, `CockpitSlotDetail.tsx`), each
carrying an explicit "KEEP IN SYNC … never edit the original (demo-frozen)" header.

---

## 1. Capability Matrix

Legend: ✅ present · ❌ absent · ◐ present but differs.

| Capability | Planning Board (`PlanningBoard.tsx`) | Planning Cockpit (`PlanningCockpit.tsx`) | Notes / cite |
|---|---|---|---|
| **Live week-grid** (bays × weeks, sticky header/first-col) | ✅ `LivePlanningBoard` grid (PlanningBoard.tsx:1027-1137) | ✅ identical markup (PlanningCockpit.tsx:422-527) | Same table, same `cellFor`/`laneForBay`. |
| **Press/Vacuum lane group rows** | ✅ (PlanningBoard.tsx:1041-1052) | ✅ (PlanningCockpit.tsx:435-446) | Same `showLane` derivation. |
| **Drag pool→cell (schedule)** w/ no-ETA client guard + 409 reject | ✅ `dropOnCell`/`schedule` (PlanningBoard.tsx:841-890) | ✅ same `dropOnCell` (PlanningCockpit.tsx:204-246) | Identical guard text + 409 toast. |
| **Drag cell→cell (move)** | ✅ (PlanningBoard.tsx:843-860) | ✅ (PlanningCockpit.tsx:206-221) | Same `move(...)`. |
| **Drag cell→pool (unschedule)**, perm-gated | ✅ `dropOnPool` (PlanningBoard.tsx:892-906) | ✅ same `dropOnPool` (PlanningCockpit.tsx:248-262) | Same `canUnschedule` gate. |
| **Panel-drag → bay drop** (`icb:panel-drag` event) | ✅ (PlanningBoard.tsx:1083-1095) | ✅ + auto-opens the dock so drop targets mount (PlanningCockpit.tsx:170-177, 474-487) | Cockpit adds a UX nicety the Board lacks. |
| **KPI capacity footer** (Filled / Empty / Value / Gap-vs-target) | ✅ (PlanningBoard.tsx:1124-1135) | ✅ same `FooterRow` (PlanningCockpit.tsx:514-525) | `FooterRow` re-implemented in cockpit `badges.tsx`. |
| **Source filter** (All / Quote-born / Workbook) | ✅ (PlanningBoard.tsx:916-928) | ✅ (PlanningCockpit.tsx:282-294) | Identical. |
| **Window nav** (‹ › · Jump-to-month · Today) | ✅ (PlanningBoard.tsx:930-946) | ✅ (PlanningCockpit.tsx:295-311) | Identical. |
| **SourceBadge / ChassisBadge** (WB·Q · ETA-committed) | ✅ module-private (PlanningBoard.tsx:1194-1221) | ✅ re-impl in `cockpit/badges.tsx:8-33` | **Duplicate definition** (split-brain risk). |
| **Awaiting-Planning-ack candidate cards** (cyan, pulsing) | ✅ (PlanningBoard.tsx:965-982) | ✅ (PlanningCockpit.tsx:361-378) | Same `ackCandidates`. |
| **PlanningAckPanel modal** | ✅ (PlanningBoard.tsx:1179-1187) | ✅ reused as-is (PlanningCockpit.tsx:614-622) | Shared component. |
| **Slot detail** (chassis-received tick, revert, JobCardSections, View-in-Production) | ✅ `LiveSlotDetail` in a **SidePanel overlay** (PlanningBoard.tsx:1152-1177, 1225-1341) | ◐ `CockpitSlotDetail` inline in a **persistent inspector pane** (PlanningCockpit.tsx:533-576; CockpitSlotDetail.tsx) | Behaviour identical; only the container differs (overlay vs docked). Cockpit adds **Pin** (PlanningCockpit.tsx:540-547). |
| **Bay-model lanes** (Parking · Pre-Assembly · Merge · Awaiting-QA) | ✅ always mounted below the grid (PlanningBoard.tsx:1143) | ◐ same `<BayModelLanes/>` but inside a **collapsed-by-default** dock (PlanningCockpit.tsx:587-603; default `dockOpen:false` useCockpitLayout.ts:31) | **Same component, less discoverable** in the Cockpit. |
| **Collapsible rails / Max-hero / Focus (native fullscreen)** | ❌ | ✅ Cockpit-only (`useCockpitLayout.ts`; toolbar PlanningCockpit.tsx:316-334) | New layout affordances; localStorage-persisted (fullscreen session-only). |
| **localStorage layout persistence** | ❌ | ✅ `icb:cockpit:layout` (useCockpitLayout.ts:22,54-60) | |
| **Mock/offline mode** (`mode!=='live'`) | ✅ full `MockPlanningBoard` w/ bundled seed, repair-WO purple, material-risk `PackageX`, legacy chassis tick (PlanningBoard.tsx:94-595) | ❌ Cockpit shows a **"use the classic board" notice** (PlanningCockpit.tsx:101-118) | **Cockpit is live-only.** Board remains the offline-demo path. |
| **Mock-only: material-lead-time-risk icon** (`PackageX`) | ✅ (PlanningBoard.tsx:531-535) | ❌ | Mock-board only; not in live board either. |
| **Mock-only: repair-WO purple + Wrench** | ✅ (PlanningBoard.tsx:521-525) | ❌ | Mock-board only. |
| **Demo Tooltips** (`<Tooltip k=…>` wrappers on grid/pool/nav) | ✅ throughout the mock board + footer | ◐ only the KPI footer is tooltip-wrapped (via `FooterRow tooltipKey`); grid/pool cells are **not** | Cockpit drops most of the guided-demo tooltip scaffolding. |
| **"Add stub Job" button** | ✅ mock board only (PlanningBoard.tsx:351-353, 319-325) | ❌ | Mock affordance. |
| **Cross-page sync** (`icb:planning-refetch`, refetch-on-focus) | ✅ (PlanningBoard.tsx:775-783) | ✅ identical (PlanningCockpit.tsx:160-165, `useRefetchOnFocus`) | |
| **Middle-mouse drag-to-pan** | ✅ (PlanningBoard.tsx:44-83) | ✅ duplicated verbatim (PlanningCockpit.tsx:37-76) | **Duplicate helper.** |

**Net:** the Cockpit is a near-superset of the **live** Board (same data, same mutators,
plus collapsible layout + Focus mode + inspector-pin + dock-auto-open). It is **not** a
superset of the **mock** Board: offline mode, material-risk/repair visuals, the guided-demo
tooltip layer, and the "Add Job" stub live only on the Board. There are **no new
capabilities the Board lacks that a planner would miss** — the deltas are layout/UX, not new
planning power.

---

## 2. Integration — v4.36c QC inbox (`/admin/qc`, `QcInspector.tsx`)

**Coexist coherently — no conflict.** The two are orthogonal surfaces:

- The QC inbox is **not** a Planning route. It lives under the admin dispatcher
  `/admin/:resource` keyed `'qc'` (`AdminModule.tsx:28`), reached from a top-level **QC** nav
  entry repointed to `/admin/qc` (TopNav.tsx:71, `perm:'qc.signoff'`). The Cockpit is the
  `/planning/cockpit` leaf of the **Planning** dropdown (TopNav.tsx:235-236).
- **Nav independence:** the Planning dropdown only ever lists Board + Cockpit
  (TopNav.tsx:235-236); it has no QC item, and QC's nav button is a sibling, so adding the
  Cockpit dropdown did **not** disturb the QC entry. Distinct routes, distinct gates
  (`planning.view` vs `qc.signoff`).
- **Shared primitive, not shared surface:** the QC inbox uses the **same `AgeingPill`**
  visual-integrity primitive (QcInspector.tsx:21) that BayModelLanes uses — so the Cockpit's
  Awaiting-QA dock and the QC inbox are visually consistent, but there is no routing/state
  coupling.
- **Hand-off:** the bay-model **Awaiting-QA** zone (rendered in the Cockpit dock via
  `BayModelLanes`) is what *feeds* the QC inbox; a planner in the Cockpit moves a job to
  Awaiting-QA, Kenny picks it up at `/admin/qc`. Coherent flow, no overlap.

**Verdict: coexist cleanly. No nav/route/state conflict.**

---

## 3. Integration — v4.36b visual-integrity flags (`services/visual_integrity.py`, `FlagBadge` / `AgeingPill`)

**Flags reach the Cockpit ONLY through the bay dock — and that dock is collapsed by
default. The week-grid/inspector carry no flags (parity with the Board, which is also
flag-free in its grid).**

- `FlagBadges` + `AgeingPill` are imported and rendered **inside `BayModelLanes`**
  (BayModelLanes.tsx:21-23, 465, 557-590; `useFlaggedBays`). Both Board and Cockpit mount
  `<BayModelLanes/>`, so the bay-tile flag badges **do** surface in the Cockpit — **but only
  when the user expands the bottom dock** (`dockOpen` defaults to `false`,
  useCockpitLayout.ts:31; dock at PlanningCockpit.tsx:587-603).
- **The week-grid carries no visual-integrity flags on EITHER surface.** A targeted grep of
  `PlanningBoard.tsx` for `FlagBadge|AgeingPill|visual_integrity|useFlag` returns **no
  matches** — the live grid's only per-cell affordances are `SourceBadge`/`ChassisBadge`.
  (The mock board's `Truck`/`PackageX` cell icons are mock-data overlays, not the v4.36b flag
  service.) So this is **not a Cockpit regression vs the Board** — it is a pre-existing
  property: flags live in the bay model, not the timeline.
- **The nav-level aggregate flag badge is global** (TopNav.tsx:93, 132-143, `useFlagSummary`
  → `/admin/health-check`) and therefore shows identically on the Cockpit page.

**Gap (confirmed, as flagged in the brief, with a nuance):**
The Cockpit does surface bay flags **via the same `BayModelLanes`**, so it is *not* a hard
gap — but because the dock is **collapsed by default**, flags are **less discoverable** in
the Cockpit than on the Board (where `BayModelLanes` is always visible below the grid). A
planner who never opens the dock sees no bay flags. **This is the one real
integration-quality delta to weigh.**

---

## 4. Integration — v4.38 FeedbackWidget

**Renders correctly. No gap.** The Cockpit route is wrapped in `<Layout>`
(`App.tsx:37` → `<Route path="/planning/cockpit" element={<Layout><PlanningCockpit /></Layout>} />`),
and `Layout` mounts `<FeedbackWidget/>` for every child (Layout.tsx:3,22). So the global
"Report issue" launcher appears on the Cockpit exactly as on every other `/mes-app/*`
screen. One caveat unrelated to routing: the widget's html2canvas screenshot is fired from a
click handler and excludes `data-feedback-ui`; the Cockpit's native-**fullscreen** Focus mode
puts only the cockpit root into the Fullscreen API (useCockpitLayout.ts:69-77) — the widget,
being a Layout sibling outside that root, would be **outside the fullscreened element** while
Focus is active (cosmetic only; not a render/routing failure).

---

## 5. Alembic chain pre-check

**The foundation adds NO migration.** `git show --stat 7e12a24` touches exactly 7 files —
`backend/app/routers/exports.py` (the cost-breakdown PDF) + `frontend/src/App.tsx` +
`TopNav.tsx` + the 4 cockpit files. **Zero** `backend/alembic/versions/*` changes. The PDF
export is pure read-path (renders the existing costing `ctx` via WeasyPrint, ReportLab
fallback; `exports.py:777-861`) and is **independent of the Cockpit** (no cockpit↔exports
import). **Pure UI + a PDF export, as expected.**

**Current head: `0029` (`0029_chassis_records_audit_version`, single linear head).** The full
chain `…→0027_feedback_submissions→0028_qc_inspection_dispatch→0029_chassis_records_audit_version`
is single-parent throughout (each `down_revision` points to exactly one predecessor; no
multi-head). The v4.36.5/v4.36c re-point that put `0029.down_revision="0028"` is already in
this worktree's history — **no migration risk introduced by v4.36d.**

---

## Split-brain / dual-maintenance risk assessment

**Risk class: MODERATE — additive (zero blast radius today) but with a real, named
dual-maintenance liability.** The Cockpit is purely additive: a new route, a new nav leaf, no
edits to the frozen Board's behaviour, no schema, no backend coupling. Nothing breaks if it
ships or is reverted.

The liability is **forked-but-not-shared code that must move in lockstep**:

1. **Three copy-forks of Board internals**, each with a "KEEP IN SYNC … never edit the
   original" header rather than a shared import:
   - the **week-grid + pool + drag handlers** (`dropOnCell`/`dropOnPool`/`schedule`/`move`
     bodies) duplicated PlanningBoard.tsx:841-906 ↔ PlanningCockpit.tsx:204-262;
   - `SourceBadge`/`ChassisBadge`/`FooterRow` duplicated PlanningBoard.tsx:1194-1221 ↔
     `cockpit/badges.tsx`;
   - `LiveSlotDetail` → `CockpitSlotDetail` (the chassis-received / revert / View-in-Production
     logic) PlanningBoard.tsx:1225-1341 ↔ `CockpitSlotDetail.tsx`;
   - `useMiddleButtonPan` duplicated verbatim PlanningBoard.tsx:44-83 ↔ PlanningCockpit.tsx:37-76.

   Any change to the live board's scheduling rules, chassis-gate, badges, or slot panel must
   now be **applied twice or it silently diverges**. The comments acknowledge this; the
   architecture doesn't enforce it.

2. **Two planner entry points to the same live mutators.** Both call the same
   `usePlanning`/`useCostings` actions, so there is **no data split-brain** (a job
   scheduled in the Cockpit shows on the Board after refetch and vice-versa via
   `icb:planning-refetch`). The split is purely in the **view code**, not in state — which
   keeps the risk to "two UIs drift in appearance/behaviour" rather than "two UIs corrupt
   each other's data."

3. **Mock-mode asymmetry.** The Cockpit punts offline to the Board. If the demo ever runs the
   Cockpit without a reachable API, the planner is bounced to the classic board — fine as a
   fallback, but means the Cockpit cannot be the *sole* Planning surface while the mock board
   still backs offline demos.

4. **Discoverability delta (from §3):** bay-model **visual-integrity flags** are present in
   the Cockpit but hidden behind the collapsed dock; on the Board they're always visible. Not
   data split-brain, but a UX-parity gap a reviewer should consciously accept.

**What is NOT at risk:** schema (no migration), the QC inbox (orthogonal route, shared only a
visual primitive), the FeedbackWidget (renders via Layout), and the PDF export (independent
read-path). The Board is genuinely untouched (frozen).

*(Findings only — go/no-go deferred to synthesis.)*
