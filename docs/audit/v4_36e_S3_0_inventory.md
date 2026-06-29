# v4.36e §3.0 — Dispatch Zone Inventory (Subagent A)

**Scope:** Read-only inventory of the REVERTED frontend dispatch zone, reconstructed from the
three reachable commits. The re-land design is NOT proposed here.

- `292ffb5` — original ADD ("Planning Board dispatch zone + useBayModel allSettled resilience")
- `e69483d` — fix ("decouple the dispatch fetch — revert the allSettled shared-refresh regression")
- `b49675d` — REVERT ("REVERT the dispatch zone to green; planning-board flex regression")

The zone's **final pre-revert form** = `git show b49675d^:<file>` (= the e69483d decoupled shape).
The **revert diff** `git show b49675d` shows exactly what was removed.

Branch under inventory: `feat/v4.36e-dispatch-zone` (HEAD `b2b55f2` = v4.36d Cockpit #60, has v4.36c QC backend).

---

## 1. STRUCTURE — what IS the dispatch zone?

A single full-width **`<Card data-testid="dispatch-zone" className="col-span-2">`** rendered in
`frontend/src/screens/Planning/BayModelLanes.tsx`, placed **immediately after the Awaiting-QA zone**
(workflow PARKING → ASSEMBLY → AWAITING QA → DISPATCH).

- Adjacency (pre-revert form, `b49675d^:BayModelLanes.tsx`): the Awaiting-QA zone is
  `data-testid="awaiting-qa-zone"` `col-span-2` at **line 660**; the dispatch zone follows at **line 710**;
  both live in the SAME flex column below the week grid. The `{/* DISPATCH zone */}` comment is at line 707.
- **Chassis shown:** `status='dispatched'` (QC-passed, released for customer collection). Backend filters
  `ChassisRecord.status == "dispatched"` (`qc.py:101`).
- **Read-only (NOT interactive):** "no drag-back — the rework loop is Phase 2+" (comment, 292ffb5
  `BayModelLanes.tsx`). Contrast the sibling Awaiting-QA zone, which IS a drop target (it carries
  `ring-2 ring-sky-500` on `qaDragActive`, line 662); the dispatch zone has **no drag/drop handlers** and
  no ring — purely a display Card.
- **Visual language** (mirrors Awaiting-QA, but green vs sky): header row
  `<span ...uppercase tracking-wide text-muted>Dispatch</span>` + `{dispatched.length} chassis` count.
  Three render branches: error → empty → list.
- **Per-chassis tile:** `<div data-testid="dispatch-chassis" data-id={c.chassis_id}
  className="w-[184px] rounded-md border border-line border-l-4 border-l-status-green bg-status-green/5 p-2">`
  showing `vin` (mono) + a green `DISPATCH` pill, `customer_name`, and `make model · job_number`.
- **Empty state:** dashed-border "No chassis dispatched yet." Tiles laid out `flex flex-wrap gap-2`.

JSX as removed by the revert (`git show b49675d`, BayModelLanes.tsx — verbatim):

```tsx
{/* WO v4.36c §3.5 — DISPATCH zone: full-width, below Awaiting QA (workflow PARKING → ASSEMBLY →
    AWAITING QA → DISPATCH). QC-passed chassis released for customer collection. Read-only in MVP
    (no drag-back — the rework loop is Phase 2+). Mirrors the Awaiting-QA zone's visual language. */}
<Card data-testid="dispatch-zone" className="col-span-2">
  <div className="mb-2 flex items-center justify-between">
    <span className="text-sm font-semibold uppercase tracking-wide text-muted">Dispatch</span>
    <span className="text-[11px] text-muted">{dispatched.length} chassis</span>
  </div>
  {dispatchError ? (
    <div data-testid="dispatch-zone-error"
      className="rounded-md border border-dashed border-status-amber/50 bg-status-amber/5 p-4 text-center text-xs text-status-amber">
      Couldn't load the dispatch list — the other zones are unaffected; it retries on the next refresh.
    </div>
  ) : dispatched.length > 0 ? (
    <div className="flex flex-wrap gap-2">
      {dispatched.map((c) => (
        <div key={c.chassis_id} data-testid="dispatch-chassis" data-id={c.chassis_id}
          className="w-[184px] rounded-md border border-line border-l-4 border-l-status-green bg-status-green/5 p-2">
          <div className="flex items-center justify-between">
            <span className="font-mono text-xs font-semibold">{c.vin || '—'}</span>
            <span className="rounded px-1 text-[10px] font-medium bg-status-green/15 text-status-green">DISPATCH</span>
          </div>
          <div className="truncate text-xs text-body">{c.customer_name || '—'}</div>
          <div className="truncate text-[11px] text-muted">
            {[c.make, c.model].filter(Boolean).join(' ') || '—'}
            {c.job_number ? ` · ${c.job_number}` : ''}
          </div>
        </div>
      ))}
    </div>
  ) : (
    <div className="rounded-md border border-dashed border-line p-4 text-center text-xs text-muted">
      No chassis dispatched yet.
    </div>
  )}
</Card>
```

NOTE — in the FINAL pre-revert form (`b49675d^`, the e69483d shape) the error guard is `dispatchError`
(local state). In the FIRST cut (292ffb5) it was `errors.dispatched` (from the hook). Same testids
(`dispatch-zone`, `dispatch-zone-error`, `dispatch-chassis`) throughout.

---

## 2. DATA + MUTATIONS

- **Read-only.** The zone GETs `/api/qc/dispatched` and only renders. No POST/PUT/PATCH; no drag → no
  mutation path. (The only QC mutation, `rec.status = "dispatched"`, lives server-side in QC sign-off
  `qc.py:200`, not in this zone.)
- **Row shape `AwaitingQaRow`** (`frontend/src/screens/Chassis/types.ts:45-52`) — REUSED, not a new type
  (the dispatch feed mirrors the awaiting-qa feed): `chassis_id: number`, `vin?`, `make?`, `model?`,
  `customer_name?`, `job_number?` (all `string | null`). This interface was NOT removed by the revert
  (shared with the Awaiting-QA zone).

### Backend — CONFIRMED PRESENT IN THE WORKING TREE ON MAIN (HEAD `b2b55f2`):

- **Service** `backend/app/services/qc.py:95` — `def list_dispatched(db: Session) -> list[dict]:`
  > "Dispatch-zone feed (§3.5): live chassis in 'dispatched', newest first. Mirrors list_awaiting_qa."
  - SELECTs `ChassisRecord.id, vin, make, model, customer_name` + `ProductionJob.job_number`
    (outer-join on `ProductionJob.chassis_record_id`), WHERE `status == "dispatched"` AND
    `deleted_at IS NULL`, `ORDER BY id DESC`. Returns dicts keyed `chassis_id, vin, make, model,
    customer_name, job_number` — matching `AwaitingQaRow` exactly. (`qc.py:95-106`)
- **Route** `backend/app/routers/qc.py:39-42` — `@router.get("/dispatched")` →
  `def qc_dispatched(db = Depends(get_db), user: User = Depends(require_user))` → `return _qc.list_dispatched(db)`.
  > "Dispatch-zone feed (§3.5) — live chassis in 'dispatched'."
  - Auth: `require_user` only (any authenticated user — read endpoint, no extra role gate).

Backend is shipped + CI-proven (v4.36c, PR #57, on main). The re-land needs ONLY frontend work.

---

## 3. FILES TOUCHED (per commit)

| Commit | File | Change |
|---|---|---|
| **292ffb5** (ADD) | `frontend/src/screens/Planning/BayModelLanes.tsx` | +41/−4: imports `AwaitingQaRow`; destructures `dispatched, errors` from `useBayModel`; adds the `dispatch-zone` Card (error guard = `errors.dispatched`). |
| **292ffb5** | `frontend/src/screens/Planning/useBayModel.ts` | +76/−32: adds `dispatched` + `errors` to `BayModel` iface + return; rewrites `refresh()` `Promise.all` → `Promise.allSettled` (adds 4th fetch `/api/qc/dispatched`); per-zone `console.warn` + `errors` flags; `mode='mock'` only when BOTH core fetches fail. |
| **e69483d** (FIX) | `frontend/src/screens/Planning/useBayModel.ts` | −76/+ reverts the hook fully back to the §3.4 `Promise.all` 3-fetch shape; drops `dispatched`/`errors` from iface + return. |
| **e69483d** | `frontend/src/screens/Planning/BayModelLanes.tsx` | re-adds `apiGet` import; replaces the hook-destructure with a local mount-only `useEffect` fetching `/api/qc/dispatched` into local `dispatched`/`dispatchError` state; swaps the JSX guard `errors.dispatched` → `dispatchError`. |
| **b49675d** (REVERT) | `frontend/src/screens/Planning/BayModelLanes.tsx` | **−53/+2 (net −51)**: removes `apiGet` import + `AwaitingQaRow` import; removes the local `useEffect`/`dispatched`/`dispatchError`; removes the entire `dispatch-zone` Card. Back to green §3.4 state. |

**No `useBayModel.ts` change in the revert** — e69483d had already restored it to the §3.4 `Promise.all`
form, so the revert only had to strip the local fetch + JSX from `BayModelLanes.tsx`.

**No test files touched by any of the three commits** (full `--name-only` lists verified). Per 292ffb5's
commit body (§0.16): the frontend has NO vitest/RTL runner, so the resilience was to be Playwright-verified
in §3.6 (abort `/api/qc/dispatched` → assert other zones still render + dispatch error shows) — that
journey was never landed (zone reverted first). No backend test was touched either.

---

## 4. `useBayModel` data-loading HISTORY (the three states)

1. **§3.4 baseline (pre-292ffb5):** `refresh()` = one `try/catch` around `Promise.all([bays, chassis,
   awaiting-qa])` (3 fetches). On ANY rejection → catch → blank all zones + `mode='mock'`. Journey-passing.
   Re-run on tab focus via `useRefetchOnFocus`.

2. **292ffb5 — `Promise.allSettled` in the shared refresh:** added `/api/qc/dispatched` as the **4th fetch**
   inside `useBayModel.refresh()`; switched `Promise.all` → `Promise.allSettled` so a single rejection
   couldn't blank everything; added `errors: {bays, chassis, awaitingQa, dispatched}` + per-zone
   `console.warn`; `mode='mock'` ONLY if both core fetches fail. (CAUTION-b "silent-deferral" hardening.)
   **Why reverted (per e69483d body):** the shared `refresh()` re-runs on tab focus; the extra 4th fetch
   slowed it enough that focus-driven re-renders kept reflowing the Planning Board's shared scroll area —
   the week-grid slot-cells "never settled" ("element not stable"), **failing 7 planning journeys
   deterministically (twice)**.

3. **e69483d — DECOUPLED mount-only fetch:** reverted `useBayModel` fully back to the §3.4 `Promise.all`
   3-fetch floor (untouched), and moved the dispatch fetch into a **local mount-only `useEffect` in
   BayModelLanes** (`let live = true` cleanup guard; `apiGet<AwaitingQaRow[]>('/api/qc/dispatched')` →
   local `dispatched`/`dispatchError`). Described as a STRONGER CAUTION-b than allSettled (a dispatch
   failure can't touch the core zones at all) and NOT focus-refetched (mount-only → no shared-scroll
   reflow churn; refreshes on nav). **Why reverted (per b49675d body):** even with the data path fully
   decoupled, the journeys STILL broke — root cause re-diagnosed as the zone's **LAYOUT impact, not the
   data path**: the week grid is a `flex-1` child of PlanningBoard's flex column (`PlanningBoard.tsx:1018`)
   and BayModelLanes renders below it in the SAME column; a SECOND full-width `col-span-2` zone (dispatch,
   on top of the existing awaiting-qa zone) grows BayModelLanes enough to squeeze the `flex-1` week grid,
   whose sticky-header table then reflows and the slot-cells never settle.

4. **b49675d — REVERT to green:** stripped the zone from `BayModelLanes.tsx`. Backend (`list_dispatched`
   + `/api/qc/dispatched`) kept shipped + CI-proven. Layout fix deferred (needs a trace; neither CA1 nor
   BA can run journeys locally — ADR 0011).

**Net for the re-land:** the open problem is the **flex-column layout regression** (a 2nd full-width zone
squeezing the `flex-1` week grid), NOT the data path. Both data approaches (allSettled-in-hook, and
decoupled mount-effect) were tried; the decoupled mount-only effect is the last/strongest data shape and
is layout-agnostic, so it's the cleaner data starting point. (Design recommendation deliberately omitted
per scope.)
