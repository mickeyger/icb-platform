# v4.36d Cockpit Promotion — §3.0 Adversarial Review (Subagent B)

**Scope:** worktree `C:/Users/micge/Documents/icb-platform-v4.36d/` @ commit `7e12a24`
(branch `feat/v4.36d-cockpit-promotion`). Foundation = additive Planning Cockpit
(`frontend/src/screens/Planning/cockpit/*`), Planning nav DROPDOWN (`TopNav.tsx`),
+426-line cost-breakdown PDF export (`backend/app/routers/exports.py`).

Severity legend: **[blocker]** ships broken / breaks CI / security · **[should-fix]**
real defect, schedule before merge · **[nice-to-have]** polish.

---

## ITEM 1 — NAV-DROPDOWN: the `nav-planning` trigger no longer navigates  **[blocker]**

### Evidence
- `TopNav.tsx:212-225` — the element carrying `data-testid="nav-planning"`
  (rendered as `nav-${entry.k.replace('nav.','')}`, k=`nav.planning`) is a
  `<button onClick={toggle}>` with `aria-haspopup="menu"`. **It opens a dropdown;
  it does not navigate.**
- `TopNav.tsx:108-110` — only the `/planning` entry is swapped for
  `<PlanningNavDropdown>`; every other nav entry stays a `<NavLink>`.
- `TopNav.tsx:235-236` — the actual board link is now a nested
  `<PlanningMenuItem to="/planning" exact title="Board">`; the cockpit is
  `to="/planning/cockpit" badge="beta"`.
- There is exactly **one** `nav-planning` render path — no separate mobile menu
  (grep across `frontend/src` returns only `TopNav.tsx` + a capture script).
  So the break is total: there is no alternate route to the board via that testid.

### Blast radius — 13 journeys click `nav-planning` then assert a BOARD surface
All break identically: the click opens a menu, navigation never fires, the awaited
board surface never mounts → `expect(...).to_be_visible` times out.

Two assertion sub-styles (both broken):

**(A) assert the heading `name="Planning Board"` — 6 files**
| journey | line |
|---|---|
| `test_planning_drag_journey.py` | 22-23 |
| `test_unschedule_revert_journey.py` | 155-156 |
| `test_dealer_capture_journey.py` | 72-73 |
| `test_planning_ack_lock_journey.py` | 86-87 |
| `test_prejob_ack_journey.py` | 22-23 |
| `test_job_number_journey.py` | 61-62 |

**(B) assert a board-mounted testid (`bay-model` / `slot-cell`) — 7 files**
| journey | line | asserts |
|---|---|---|
| `test_bay_model_journey.py` | 51-52 | `bay-model` |
| `test_chassis_moved_to_awaiting_qa_journey.py` | 83-84 | `bay-model` |
| `test_chassis_return_to_parking_journey.py` | 89-90 | `bay-model` |
| `test_cross_page_sync_journey.py` | 38-39 | `bay-model` |
| `test_planning_drag_to_merge_journey.py` | 175-176 | `bay-model` |
| `test_production_dashboard_journey.py` | 115-117 | `slot-cell` |
| `test_job_card_modal_journey.py` | 84-85 | `slot-cell` |

(The original WO said "~7" — the true count is **13**. The "~7" likely referred
only to the heading-style group, which is 6.)

### Option (a) — update the journeys to click `nav-planning` → "Board" menu item
- Each of the 13 needs **one inserted line** after `nav.click()`:
  `page.get_by_role("menuitem", name="Board").click()` (or a `to="/planning"`
  locator). The subsequent board assertion is then reached unchanged.
- A shared helper exists in **only one** of the affected files
  (`test_planning_drag_journey.py::_open_board`); the other 12 inline the
  nav-click. So this is **13 near-identical edits** (≈13-26 lines), no shared
  refactor available without first extracting a common helper.
- **Adversarial against (a):** it bakes the dropdown's existence into 13 test
  files. If §3.x later promotes the Cockpit to the default Planning surface (a
  live strategic possibility — see below), all 13 get re-touched again. We'd be
  paying the migration cost twice.
- **For (a):** it is the *honest* test of the shipped UX. The nav genuinely now
  requires two clicks; tests should reflect product reality, not paper over it.

### Option (b) — split-button: `nav-planning` navigates to `/planning` by default AND offers the menu
- UX: a `<NavLink to="/planning">` for the label + a sibling caret `<button>` that
  opens the menu (two hit-targets in one control). Restores single-click-to-board
  → **all 13 journeys pass unmodified.**
- Code complexity: **moderate.** The current dropdown already manages
  open/coords/outside-click/reflow (`TopNav.tsx:176-241`); splitting the trigger
  means the testid must move to a deliberate target. Two sub-options:
  - keep `data-testid="nav-planning"` on the **navigating** half → journeys pass
    AND the menu is still reachable via the caret. **This is the cheapest green.**
  - put the testid on the caret → journeys still break. (Don't.)
- **Adversarial against (b):** a split-button is a heavier a11y contract (two
  focusable children, arrow-key semantics, `aria-haspopup` on the caret only).
  Done sloppily it's worse than the plain dropdown. Also: it quietly asserts
  "Board is the canonical Planning surface", which pre-judges the strategy
  question below.
- **For (b):** zero test churn, and single-click-to-board matches **5 years of
  muscle memory** for planners — the dropdown adds a click to the single most-used
  nav path in the app.

### Strategic question — is the dropdown the destination, or is the Cockpit?
The Cockpit is explicitly **beta / additive** (`PlanningCockpit.tsx:1-9`,
`TopNav.tsx:236` `badge="beta"`), and the original `/planning` board is
**demo-frozen** (DUPLICATED, "never edit the original" — `PlanningCockpit.tsx:7-9`,
`badges.tsx:2`, `CockpitSlotDetail.tsx:3`). The duplication is a deliberate
de-risking move for *this* demo, not a long-term architecture. Two futures:
1. **Cockpit wins** → `/planning` eventually redirects to the cockpit; the board
   is retired. Then the *right* nav is a single `nav-planning` → `/planning`
   (which renders the cockpit), and the dropdown is transitional scaffolding.
2. **Both persist** (board for offline/mock, cockpit for live — see
   `CockpitMockNotice`, `PlanningCockpit.tsx:101-118`) → a dropdown is justified
   long-term.

Given the cockpit cannot run offline (`mode !== 'live'` → mock notice), future #2
has a real basis — **but** that's a fallback, not a co-equal surface. The likely
end-state is #1.

### VERDICT — **Option (b), testid on the navigating half.**
Rationale: (1) it is the **cheapest path to green** (0 journey edits vs 13);
(2) it preserves single-click-to-board, the highest-traffic nav action, which the
plain dropdown regresses; (3) it is **strategy-neutral** — if the Cockpit later
becomes default, `/planning` simply renders it and the split-button still points
"home" with zero test rework, whereas option (a) would have hard-coded a two-click
dance into 13 files that then needs unwinding. Keep the caret → menu for Cockpit
discovery. **Do NOT ship the current pure-dropdown**: it is a 13-journey CI break
*and* a daily-driver UX regression. If (b) is rejected on a11y grounds, fall back
to (a) but extract a single `_open_board()` helper into `_common.py` first so the
two-click sequence lives in one place (cushions the future promotion).

---

## ITEM 2 — DRAG-DROP coverage in the Cockpit  **[should-fix: a11y]**

**Implemented (mouse/HTML5 DnD):** scheduling drag/drop is FULLY wired and reuses
the board's mutators.
- pool→cell schedule + cell→cell move: `PlanningCockpit.tsx:204-246` (`dropOnCell`),
  guards `getChassisState(job)==='none'` (no-ETA block, 226-232) and 409-occupied
  (238-241).
- cell→pool unschedule: `dropOnPool` (248-262), perm-gated `canUnschedule` (253).
- panel-drag → auto-opens the bay dock via `icb:panel-drag` CustomEvent
  (471-487 dispatch; 170-177 listener) — parity with the board.
- `draggable={canSchedule}` everywhere (383, 474), so read-only roles can't drag.

**GAP — zero keyboard a11y / focus states on the drag affordances  [should-fix]**
- Pool cards (`PlanningCockpit.tsx:380-403`) and slot cells (470-505) are
  `draggable` but expose **no keyboard scheduling path** — no `onKeyDown`, no
  roving tabindex, no "move to…" fallback. A keyboard-only planner cannot schedule.
- Slot cells are `<button>` (focusable) but pool cards are plain `<div>` (not
  focusable at all) — inconsistent and worse for the pool.
- No visible `:focus-visible` ring on the drag targets (only hover/selected
  styles). This is a pre-existing parity gap with the frozen board, **not a
  regression**, but the Cockpit is pitched as the *new* surface — flag it so it
  doesn't get grandfathered in. Severity: should-fix (accessibility), not blocker.

---

## ITEM 3 — ACK-MODAL + inspector focus-collapse edge cases  **[nice-to-have]**

The inspector is a persistent right pane (NOT a focus-trapping modal); the ack flow
is still the reused `PlanningAckPanel` modal (`PlanningCockpit.tsx:613-622`).

- **Inspector follows live mutations correctly:** `selectedLiveSlot` re-derives by
  id each render (155-158) and the revert handler clears selection on success
  (564). Good.
- **Collapse-while-selected edge case (minor):** `rightExpanded =
  !rightCollapsed || !!selectedLiveSlot || pinned` (267). If a job is selected the
  pane **cannot be collapsed** (the collapse toggle is rendered, but `rightExpanded`
  stays true because `selectedLiveSlot` is truthy) — clicking "collapse" appears to
  do nothing until the user also clears the selection. Confusing but not harmful.
  **[nice-to-have]**
- **Stale-selection silent-empty:** if the selected slot's job is unscheduled from
  *another* surface (cross-page sync refetch), `selectedLiveSlot` becomes `null`
  and the pane silently falls back to the "No job selected" EmptyState (553-574)
  with no "the job you were viewing moved" notice. Acceptable, but it's a quiet
  state change. **[nice-to-have]**
- Revert textarea is correctly bounded (`slice(0,500)` + `maxLength=500`,
  `CockpitSlotDetail.tsx:94-95`).

---

## ITEM 4 — `_cost_breakdown_pdf_reportlab` (exports.py +426) — ADVERSARIAL

### (a) Data-source authority + RBAC  **[OK — gated]**
- Triggered ONLY from `GET /results/{record_id}/export/pdf`
  (`exports.py:777-861`); the reportlab fn is the WeasyPrint fallback (846-847).
- **Auth is enforced:** `get_current_user` → 401 (779-781), then
  `user_can(user, "export.pdf", db)` → 403 (782-783). The function reads only the
  caller-supplied `record_id`'s `CalculationRecord` (+ its `TrailerType`,
  `Customer`) — `dimensions_json`, `result_json` (789-790),
  `strip_excluded_items` applied (791). No cross-record bleed. **RBAC aligned.**
- ⚠ **No per-record ownership check.** The gate is the global `export.pdf`
  permission; any role holding it can export *any* `record_id` (IDOR-shaped). This
  mirrors the sibling `report_for_record` (864+, gated on `quote.generate`) so it's
  a **consistent existing posture**, not new — but worth a one-line confirmation
  that `export.pdf` is intended as an any-record grant. **[should-fix: confirm
  intent]**

### (b) Injection vectors (reportlab `Paragraph` parses XML markup)  **[OK — escaped]**
Free-text / user-influenced strings rendered inside `Paragraph` are **all escaped**
via `xml.sax.saxutils.escape` (imported 443):
- `trailer_name`, `record_id`, `created_at_human` (498-502)
- `customer_name` (513-514)
- BOM `material`, `formula` (573, 575)
- chassis `label` (617)

**Not an injection vector (verified, not assumed):**
- Chassis header `axle_count / tyre_style / tyre_count / length` (610-612) is
  built with raw `%s` and NOT escaped — BUT these are server-derived from a
  constrained catalogue (`services/__init__.py:450-493`: `axle_count` is
  `int(...)`, `tyre_style ∈ {dual, super_single}`, counts are computed). Not
  free-text → no realistic injection. Cosmetic-only risk if data ever loosened.
  **[nice-to-have: wrap in escape() defensively]**
- `material_code` (577), `unit` (578), chassis `kind` (616) are passed as **raw
  strings into table cells, NOT wrapped in `Paragraph`** → reportlab treats them
  as literal text (no XML parse) → no injection. An `&` would render literally
  (cosmetic). Acceptable.

**Verdict: no exploitable injection.** The escape() discipline is correct on every
Paragraph that carries user free-text.

### (c) Triggering route + role-gate
Covered in (a): `export_pdf` (777), `export.pdf` permission (782). The reportlab
helper itself is pure (takes a pre-built `ctx` dict, no DB/request access) — it
cannot be reached unauthenticated.

### (d) Empty-state / missing-data / zero-rows  **[OK — defensive]**
- Empty BOM: `for it in ctx.get("items") or []` (561) → header-only table, no crash.
- No chassis: `if chassis and chassis.get("items")` (609) → section skipped.
- No category totals / no customer / no discount: all `if`-guarded (512, 649, 695).
- Numbers: `_fmt2` swallows `TypeError/ValueError` (457-460); discount coerced with
  try/except (691-694). Robust.
- ⚠ **Outer 500-on-any-exception (835-861):** the whole render is wrapped; on
  failure it `traceback.print_exc()` + raises `HTTP 500` with **`detail=f"...{exc}"`
  echoing the raw exception string to the client.** That leaks internal error text
  (paths, lib internals) into an HTTP response body. **[should-fix: don't echo
  `exc` to the client]** — this is the one genuine exports.py defect.

---

## ITEM 5 — Cockpit empty-state / no-jobs / cross-day-week boundary  **[OK, minor]**

- **No weeks:** `board.weeks.length === 0` → `<EmptyState>` (416-420). Good.
- **Empty pool:** "All scheduled." (404). Good.
- **No job selected:** inspector EmptyState (572-573). Good.
- **Offline/mock:** dedicated `CockpitMockNotice` with a link back to the board
  (101-118) — the cockpit refuses to run on mock data and says so. Good (and is
  itself the answer to whether the dropdown is permanent — see Item 1 strategy).
- **Cross-week/day boundary:** the grid is keyed purely on `board.weeks` /
  `week_key` (449, 451) from the server; `nextMonths(12)` drives the jump-select
  (305). No client-side date arithmetic that could drift across midnight except
  `todayIso()` (627-633), used only as the `received_at` for a chassis tick — uses
  **local** `getDate()`, so a tick made near midnight in a non-UTC TZ could record
  the wrong calendar day. Pre-existing pattern, low impact. **[nice-to-have]**

---

## ITEM 6 — SILENT-DEFERRAL audit  **[OK — no defect found]**

Traced every cockpit mutator's error path to ground:
- `dropOnCell` / `dropOnPool` catch only 409 (`PlanningCockpit.tsx:214, 238`) — but
  the context wrappers (`PlanningContext.tsx:171-174, 190-193, 204-207, 220-223`)
  call `handleApiError(e, toast.push)` **then `throw e`**. `handleApiError`
  (`api.ts:118-140`) toasts 401/403/404/422/default and **re-throws only 409**
  (line 131). Net: **non-409 errors are toasted at the context layer before the
  re-throw**, then harmlessly ignored by the cockpit's 409-only catch. **Not silent.**
- `markSlotChassisReceived` (179-188) has no try/catch, but its `markChassisReceived`
  → `pjPost` (`CostingsContext.tsx:211-233`) self-handles: toasts 409 inline and
  routes everything else through `handleApiError` **without re-throwing** (the only
  re-throw in handleApiError is 409, which pjPost intercepts *before* calling it at
  225-229). So `pjPost` never rejects → no unhandled promise, failures are toasted.
  **Not silent.**
- `revert` handler `catch { /* surfaced by the context toast */ }` (564-565) — true,
  the context toasts it. **Not silent.**
- `localStorage` writes (`useCockpitLayout.ts:54-59`) swallow quota errors silently
  — correct (non-fatal persistence, by design).

**Conclusion:** the Cockpit's terse local catches are *safe* because every mutator
surfaces its own errors upstream. No silent-deferral defect. (The only error-text
*leak* is server-side, Item 4d.)

---

## ITEM 7 — PREMISE-VS-PREDICATE sweep

1. **WO premise "Planning nav trigger navigates" → FALSE.** It opens a dropdown
   (`TopNav.tsx:212` `onClick={toggle}`). The board is now two clicks deep. → Item 1.
   This is THE foundation premise break.
2. **WO premise "~7 journeys click nav-planning" → UNDERCOUNT.** Actual = **13**
   (6 heading-style + 7 testid-style). → Item 1 table.
3. **Doc claim "touches nothing the existing /planning board relies on"
   (`useCockpitLayout.ts:3`) → TRUE for the hook, but the sibling nav change
   absolutely affects the board's reachability.** The *cockpit* is additive; the
   *nav dropdown* shipped alongside it is NOT additive — it mutates the board's
   entry point. Easy to conflate "the cockpit is safe" with "this PR is safe".
4. **Doc claim "Identical content + behaviour" (`CockpitSlotDetail.tsx:3`) vs the
   board's `LiveSlotDetail`:** the cockpit version renders inline (no SidePanel
   overlay) — so it has **no focus trap / Esc-to-close** that a modal would. Claim
   is honest about the *content*, but the a11y profile differs (Item 2/3).
5. **"Cockpit reuses the SAME live data + mutators" (`PlanningCockpit.tsx:4`) →
   TRUE and verified** (usePlanning/useCostings mutators, Item 6). Good premise.
6. **PDF "renders the *same* ctx data" via reportlab fallback
   (`exports.py:438-441`) → TRUE** — both WeasyPrint and reportlab consume the
   identical `ctx` (844 vs 847). Faithful, as claimed.

---

## Priority summary
| # | Finding | Severity |
|---|---|---|
| 1 | `nav-planning` opens dropdown, doesn't navigate → **13** journeys break + daily-driver UX regression. **Fix via split-button (b), testid on navigating half.** | **blocker** |
| 4d | `export_pdf` 500 handler echoes raw `exc` string to client (info leak) — `exports.py:858-861` | should-fix |
| 4a | No per-record ownership on `export.pdf` (IDOR-shaped; consistent w/ siblings — confirm intent) | should-fix |
| 2 | Cockpit drag has no keyboard a11y / focus-visible on pool cards + cells | should-fix |
| 3 | Inspector can't be collapsed while a job is selected; stale-selection silent-empty | nice-to-have |
| 4b | Chassis header + material_code/unit unescaped (NOT exploitable — constrained/non-Paragraph) | nice-to-have |
| 5 | `todayIso()` local-TZ midnight drift on chassis tick | nice-to-have |

**No silent-deferral defect (Item 6). No exploitable PDF injection (Item 4b).**
