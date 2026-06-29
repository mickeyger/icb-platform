# v4.36d Cockpit Promotion — §3.0 Inventory + Premise Check (Subagent C)

**Foundation commit:** `7e12a24` — "v4.36d initial — pop demo-prep Cockpit + cost-breakdown PDF export (Michael's stash, §0.18.5)"
**Branch:** `feat/v4.36d-cockpit-promotion`
**Worktree:** `C:/Users/micge/Documents/icb-platform-v4.36d/`
**Stat:** 7 files, +1442 / −56.

---

## 1. File inventory (7 files)

| # | File | Δ | What it actually contains | Integrity |
|---|------|---|---------------------------|-----------|
| 1 | `backend/app/routers/exports.py` | +426/−56 (M) | Adds `_cost_breakdown_pdf_reportlab(ctx)` (a pure-Python ReportLab A4-landscape renderer, def @433) **and** rewires the existing `export_pdf` route (@777) so a WeasyPrint `ImportError`/`OSError` falls back to it instead of hard-failing. Mirrors `templates/reports/cost_breakdown.html`. | OK — `py_compile` clean per commit msg; ReportLab is in requirements. |
| 2 | `frontend/src/App.tsx` | +3 (M) | Imports `PlanningCockpit`; adds **additive** route `/planning/cockpit` wrapped in `<Layout>`. The `/planning` (PlanningBoard) route is byte-unchanged. | OK |
| 3 | `frontend/src/components/layout/TopNav.tsx` | +154/−~14 (M) | Replaces the flat "Planning" `NavLink` with a `PlanningNavDropdown` (Board + Cockpit-`beta`); all other nav entries unchanged. Adds `useLocation`. The v4.36c.1 `/admin/qc` repoint (#59) survived the 3-way merge. position:fixed menu to escape the nav's `overflow-x-auto` clip. | OK |
| 4 | `frontend/src/screens/Planning/cockpit/PlanningCockpit.tsx` | +633 (NEW) | The 3-pane Cockpit (Concept 6): collapsible Unscheduled rail · hero week-grid timeline · persistent inspector + collapsible bay-model dock + native-fullscreen Focus Mode. See §3. | OK — all 15 imports resolve (verified). |
| 5 | `frontend/src/screens/Planning/cockpit/CockpitSlotDetail.tsx` | +120 (NEW) | The inspector body. **Explicitly self-documented as "Duplicated from PlanningBoard's private LiveSlotDetail"** (header L1-4); identical behaviour, renders inline instead of in a SidePanel overlay. Reuses shared `StatusPill`, `JobCardSections`. | OK |
| 6 | `frontend/src/screens/Planning/cockpit/badges.tsx` | +65 (NEW) | `ChassisBadge`, `SourceBadge`, `FooterRow`. **Header L1-2 explicitly: "Duplicated from PlanningBoard's private ChassisBadge / SourceBadge / FooterRow."** See §5. | OK |
| 7 | `frontend/src/screens/Planning/cockpit/useCockpitLayout.ts` | +97 (NEW) | Layout-state hook only (rail/inspector/dock collapse + fullscreen), persisted to `localStorage` key `icb:cockpit:layout`. No data, no DB. See §4. | OK |

**MISSING pieces:** none. Every import target in the 4 new files exists on disk; every named export consumed (`zarShort`/`dmy`/`monthYear`/`nextMonths`, `getChassisState`, `useRefetchOnFocus`, `ChassisState`/`PlanningJob`/`PlanningSlot`/`PlanningWeekCol`, `NavEntry`, `StatusPill`, `Tooltip`, `BayModelLanes`, `PlanningAckPanel`, `JobCardSections`) is present. Foundation is **COMPLETE**.

**EXTRA / unexpected content:** The commit subject frames exports.py as a "cost-breakdown PDF export" demo-prep item; in reality it is a **substantive backend hardening** — a 426-line ReportLab fallback that changes prod PDF behaviour (previously raised `RuntimeError("WeasyPrint is not installed.")`). The commit body already self-corrects this ("the 'fridge fix' label was imprecise … to be documented in the v4.36d §3.8 ADR"). Flag for the ADR; not a defect.

---

## 2. exports.py — `_cost_breakdown_pdf_reportlab` wiring

- **Defined:** `exports.py:433`. **Called:** `exports.py:847` — the **only** call site (grep-confirmed, 2 hits = def + call).
- **WIRED, not dead.** Reached via the existing route `GET /results/{record_id}/export/pdf` (`export_pdf`, @777).
- **COEXIST, not replace.** The diff shows the route previously did:
  ```python
  except ImportError as e:
      raise RuntimeError("WeasyPrint is not installed.") from e
  ```
  and now does:
  ```python
  try:
      from weasyprint import HTML            # primary path — UNCHANGED, still preferred
      ...
      pdf_bytes = HTML(string=html_str).write_pdf()
  except (ImportError, OSError):
      pdf_bytes = _cost_breakdown_pdf_reportlab(ctx)   # NEW fallback
  ```
  So WeasyPrint remains the primary high-fidelity renderer; the new function is the graceful degradation path for the prod host (HostAfrica cPanel/CageFS — no GTK/Pango/cairo; ADR 0017). It renders the **same `ctx`** dict, so no new data shape.
- **vs the other export functions in the file:** there are 4 routes — `export_excel` (@16, openpyxl), `export_pdf` (@777, the one touched), `report_for_record` (@864, ReportTemplate path), `report_explosive_quote_compat` (@926). `_cost_breakdown_pdf_reportlab` is a module-private helper, not a 5th route; it slots under `export_pdf` only. No overlap/conflict with the other three.
- **Read-only.** Pure read of `CalculationRecord`/`TrailerType`/customer → bytes. No writes.

---

## 3. PlanningCockpit.tsx — stated purpose vs actual capability

- **Header comment (L1-9):** "An ADDITIVE alternate Planning layout at `/planning/cockpit`: a 3-pane cockpit (collapsible Unscheduled rail · hero timeline · persistent inspector) … plus native-fullscreen Focus Mode. It reuses the SAME live data + mutators as the board (`usePlanning` / `useCostings`) … The week-grid + Unscheduled pool logic below is DUPLICATED from PlanningBoard's `LivePlanningBoard`."
- **Actual capability — fully functional, NOT a skeleton.** It:
  - branches on `usePlanning().mode` → `CockpitSkeleton` (loading) / `CockpitMockNotice` (offline) / `LiveCockpit` (live);
  - in `LiveCockpit`, consumes the real PlanningContext (`board, schedule, move, unschedule, revertToUnscheduled, jumpTo, today, nextWindow, prevWindow, refresh`) and CostingsContext (`ackPlanning, markChassisReceived`);
  - renders a live week-grid with **working drag-and-drop scheduling** (`dropOnCell` → `schedule`/`move`; `dropOnPool` → `unschedule`), the awaiting-Planning-ack rail, capacity footer rows, the inspector (`CockpitSlotDetail`), the `BayModelLanes` dock, and the `PlanningAckPanel` modal;
  - wires the same cross-page sync events as the board (`icb:planning-refetch`, `icb:panel-drag`) and `useRefetchOnFocus`;
  - honours permissions (`planning.schedule`/`unschedule`, `production.chassis_received`).
- **Verdict:** a complete, live, mutating alternate Planning surface. The header's claims match the code.

---

## 4. useCockpitLayout.ts — Rule 18 duplication check

- **NO duplication of a data hook.** `useCockpitLayout` is **layout-state only** (rail/inspector/dock collapse booleans + fullscreen + `localStorage` persistence). It performs **zero** data fetching or mutation.
- `useBayModel.ts` (`screens/Planning/useBayModel.ts:38`) is a **data** hook (loads assembly-bay floor state, assign/merge mutators). **Different concern** — no overlap. `usePlanningData`/`usePlanningContext` data lives in `store/PlanningContext.tsx`, which the cockpit consumes (not re-implements).
- There is **no pre-existing `useBoardLayout`/`usePlanningLayout`** hook for it to duplicate (grep: `useCockpitLayout` appears only in its own file + PlanningCockpit). The board keeps its layout as inline component state, so no shared layout hook existed to reuse.
- **Rule-18 verdict for this file: CLEAN.** Net-new concern; nothing to reuse.

---

## 5. badges.tsx — Rule 18 duplication check

- **DUPLICATION — confirmed and self-declared.** `cockpit/badges.tsx` (`ChassisBadge` L8, `SourceBadge` L21, `FooterRow` L36) are byte-for-byte siblings of PlanningBoard's **module-private** versions:
  - `PlanningBoard.tsx:1194` `function ChassisBadge`
  - `PlanningBoard.tsx:1209` `function SourceBadge`
  - `PlanningBoard.tsx:597` `function FooterRow`
  The header comment states it outright ("Duplicated from PlanningBoard's private … KEEP IN SYNC … never edit the original (demo-frozen)").
- **Root cause:** these three were declared `function` (module-private, not `export`) inside the frozen `PlanningBoard.tsx`, so the cockpit could not import them without editing the frozen file. The author chose copy-over-export to honour the demo freeze.
- **vs shared badge components:** `ChassisBadge`/`SourceBadge`/`FooterRow` are **Planning-board-specific** (chassis ETA pill, WB/Q source pill, capacity footer row) and do **NOT** overlap the generic shared ones — `StatusPill` (`components/ui/primitives.tsx:33`), `FlagBadge` (`components/Flag/FlagBadge.tsx`), `AgeingPill` (`components/Flag/AgeingPill.tsx:17`). `CockpitSlotDetail` already correctly reuses the shared `StatusPill`. The cockpit `badge="beta"`/`badge` chips in TopNav/PlanningCockpit are inline `<span>`s, a separate trivial concern.
- **Rule-18 verdict: FLAG (intra-Planning duplication of 3 private badges + `useMiddleButtonPan` + the week-grid markup).** Acceptable as a deliberate demo-freeze tradeoff, but it creates a KEEP-IN-SYNC liability. **Recommendation for a later §:** once PlanningBoard un-freezes, promote these 3 (and `useMiddleButtonPan`, `PlanningBoard.tsx:44`) to a shared `screens/Planning/_shared` module and have both board + cockpit import them. Not a §3.0 blocker.

---

## 6. DB-touch confirmation

- **The §3.0 foundation touches NO shared DB and writes nothing.**
  - **Frontend (5 files):** pure UI. Grep for `apiPost|apiPut|apiDelete|apiPatch|fetch(|.post(|.put(|.delete(` across `cockpit/` → **0 hits**. All mutations go through the **existing** PlanningContext/CostingsContext mutators (`schedule`/`move`/`unschedule`/`revertToUnscheduled`/`markChassisReceived`/`ackPlanning`) — the same ones the live board already uses; no new write path is introduced. `useCockpitLayout` writes only to `localStorage`.
  - **Backend (exports.py):** `export_pdf` + `_cost_breakdown_pdf_reportlab` are **read-only** — they `db.query(...)` `CalculationRecord`/`TrailerType`/customer and emit a PDF. No `add`/`commit`/`flush`/`INSERT`/`UPDATE`.
- **No new migration, no schema change, no seed change.**
- **=> No reseed required for §3.0.** It is pure additive UI + a read-only PDF-export fallback.

---

### Bottom line
Foundation **COMPLETE** (7/7 files, all imports resolve, no missing piece). exports.py PDF helper is **WIRED + COEXIST** (WeasyPrint→ReportLab fallback inside the existing `export_pdf` route, read-only). Two Rule-18 notes: `useCockpitLayout` is **clean** (net-new layout concern), `badges.tsx` + `CockpitSlotDetail` + the week-grid are a **declared intra-Planning duplication** (deliberate demo-freeze tradeoff; promote-to-shared after un-freeze). **Zero DB writes → no reseed.**
