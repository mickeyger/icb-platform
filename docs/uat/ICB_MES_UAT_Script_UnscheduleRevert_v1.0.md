# UAT — Scheduled → Unscheduled Revert (WO v4.34.2) — v1.0

User-facing UI feature: a planner/admin can move a scheduled job back to the Unscheduled pool for a
reshuffle, without rejecting the sign-off. Execute on the Planning Board. Roles: **planner** (primary)
and **admin**; **workshop** + **sales** are the negative cases.

> Setup: pick (or schedule) a job that is on a lane (Scheduled) and has **not** started in the workshop
> and has **no** QC tick yet. Note its chassis + sign-off state before you start.

## UAT-1 — Planner revert via the slot panel (happy path)

1. Sign in as a **planner**. Open **Planning Board**.
2. Click the scheduled job's cell → the slot side-panel opens.
3. Under **Re-plan**, optionally type a reason in *"Why move this back? (optional)"*, then click
   **↩ Move back to Unscheduled**.

**Expected (PASS):** the panel closes; the job disappears from its lane and reappears at the **top** of
the Unscheduled column. The job's chassis assignment and both sign-offs are unchanged (open the job and
confirm). It can be re-scheduled normally from the pool.

## UAT-2 — Reason is optional

Repeat UAT-1 but leave the reason blank and confirm. **Expected:** the revert still succeeds (a one-click
reshuffle is fine).

## UAT-3 — Drag-to-pool still works (and is now guarded)

1. As a **planner**, drag a scheduled job's cell onto the Unscheduled pool.

**Expected:** same result as UAT-1 (job returns to the pool), with no reason prompt. (This is the quick
path; it goes through the same safety rules as the panel button.)

## UAT-4 — Workshop-started job is blocked

1. Use a job that has been started in the workshop (a work order started).
2. As a **planner**, try to revert it (panel button or drag).

**Expected (PASS):** the revert is refused with a clear message ("…has started in the workshop — cannot
revert"); the job stays on its lane. (The panel button is also hidden once the job leaves 'planning'.)

## UAT-5 — QC-ticked job is blocked

1. Use a job that has at least one completed QC checklist item / sign-off.
2. As a **planner**, try to revert it.

**Expected (PASS):** refused ("…has a QC check recorded — cannot revert"); the job stays scheduled.

## UAT-6 — Workshop role: no affordance

1. Sign in as **workshop**. Open the Planning Board and click a scheduled job's cell.

**Expected (PASS):** there is **no** "Move back to Unscheduled" control in the panel. (A direct API call
would be refused with 403 — the server enforces it, not just the hidden button.)

## UAT-7 — Sales role: no affordance

Repeat UAT-6 as **sales**. **Expected:** no revert control.

## UAT-8 — Admin can revert

Repeat UAT-1 as **admin**. **Expected:** same as the planner happy path.

## Audit trail (BA/admin spot-check, optional)

Each successful revert writes one row to `icb_mes.production_jobs_audit`:

```sql
SELECT production_job_id, previous_status, new_status, previous_lane, previous_bay, user_name, reason, created_at
FROM icb_mes.production_jobs_audit ORDER BY id DESC LIMIT 10;
```

**Expected:** `previous_status='scheduled'`, `new_status='unscheduled'`, the lane/bay it came from, the
operator, and the reason (NULL for the drag/quick path, your text for the panel path). A queryable admin
explorer for this log is deferred to v4.35.

---

**Sign-off:** _______________________  **Date:** ____________
