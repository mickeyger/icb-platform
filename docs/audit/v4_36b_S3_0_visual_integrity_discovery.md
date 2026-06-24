# v4.36b §3.0 — Visual Integrity System · Discovery Synthesis

> **Sprint:** v4.36b — Visual Integrity System (RED-flag rendering + drop-gate catalog + Health Check dashboard)
> **Branch:** `feat/v4.36b-visual-integrity` (off `main` @ `457afbe`)
> **Date:** 24 Jun 2026 · **CA:** CA1
> **Artifact discipline:** §0.14 + `feedback_s30_artifact_pattern`

---

## Method note (§0.14)

- **3 parallel subagents** per the §0.13 standing rule (Michael 16 Jun PM):
  - **A — Existing validators inventory** (`chassis_integrity`, `chassis`, `planning`, `production_jobs`, `prejob_cards`, +`integrity.py`)
  - **B — Existing visual-feedback patterns** (frontend/src — badges, tooltips, toasts, animation, LocalStorage, top-nav)
  - **C — Drop-gate audit + silent-deferral sweep** (per §0.15 + `feedback_silent_deferral_as_defect`)
- **Transient failures / re-runs:** none. All three returned first-pass with full file:line citations.
- **Scope discipline:** read-only. No code changed in §3.0. The silent-deferral sweep (Subagent C task 2) **surfaces** findings only — no mid-sprint fixes (§0.15).
- **Headline:** the catalog is implementable with **NO new DB tables/columns/migrations** (§0.2 holds) — every timestamp the flags need is already persisted. The work is mostly *standing read-only age computations* over fields/events that already exist, plus extending existing visual primitives.

---

## Part A — Validators inventory + flag coverage

### A.0 Two structural facts that shape every flag
1. **No `chassis_records.production_job_id` column.** The job↔chassis link is owned by the **job side** (`production_jobs.chassis_record_id`). Every "is this chassis linked to a job" question is a back-reference query `SELECT production_jobs WHERE chassis_record_id = :id`. → `chassis_no_production_job` reuses `integrity.find_anchorless_chassis` (`integrity.py:138-157`), not a column read.
2. **No age/stale/overdue logic exists anywhere in services today.** The *only* precedent is the KPI `chassis_slipped`/`delayed/critical` block in `compute_production_kpis` (`production_jobs.py:560-563`). Every age-gated flag is at least partially new derivation — but the *rules* mostly already exist as write-time gates.

### A.1 Flag-coverage map (does an existing rule/field back each flag?)

| Flag | Status | Backing / derivation | Reads |
|---|---|---|---|
| `job_eta_overdue` | ✅ **BACKED** | Exactly `chassis_slipped` (`production_jobs.py:560-563`). **Reuse `chassis_received()` (`production_jobs.py:512-520`) verbatim.** | `production_jobs.chassis_eta`, `chassis_received_at`, chassis status |
| `bay_post_attached_stale` | 🟡 **Nearly free** | State `post_attached` already exposes `body_attached_on` on the `BayOut` payload (`_latest_body_attached_dates`, `chassis.py:675-687`). Flag = state + `today − body_attached_on > N`. | bay state + `body_attached_on` |
| `chassis_no_vin` | 🟢 NEW (rule documented) | NULL-VIN exemption is documented in `validate_vin_format` (`chassis_integrity.py:44-54`); nothing flags a long-NULL VIN. Derive `vin IS NULL AND age>24h`. | `chassis_records.vin`, `created_at` |
| `chassis_vin_format_legacy` | 🟢 NEW (regex reusable) | Re-run `VIN_RE` (`chassis_integrity.py:24`) read-only over `vin IS NOT NULL`. By the "D-VIN" ruling stored rows are never re-validated at write — so a read-time scan is the only way. | `vin`; reuse `VIN_RE`/`normalize_vin` |
| `chassis_no_customer` | 🟢 NEW | `validate_customer_consistency` only fires on a *mismatch* (`chassis_integrity.py:109-120`); blanks skip it. Derive: has back-ref job AND `customer_name` blank. | `customer_name` + back-ref job |
| `chassis_no_production_job` | 🟢 NEW (detector exists) | Reuse `find_anchorless_chassis` (`integrity.py:138-157`) + 48h age gate. | back-ref `production_jobs.chassis_record_id`, `created_at` |
| `chassis_no_make_model` | 🟢 NEW | The v4.36a.4 stub contract anchors `make=NULL` (`prejob_cards.py:140-144`); comment at `:143` literally names "v4.36b RED-flags incomplete stubs" as the consumer. Derive `status IN (expected, expected_orphaned) AND make IS NULL AND age>24h`. | `make`, `status`, `created_at` |
| `job_eta_missing` | 🟢 NEW (rule backed) | "No ETA blocks scheduling" is `eta_gate_reason` (`planning.py:119-122`) — a write-time gate, not a standing flag. Derive `status='planning' AND chassis_eta IS NULL AND not received AND age>24h` (age basis = `planning_acknowledged_at`). | `status`, `chassis_eta`, `planning_acknowledged_at` |
| `prejob_sent_stale` / `signoff_pending_long` / `signoff_role_pending_5days` | 🟢 NEW | All three derive from `prejob_cards.sent_for_check_at` (+ per-role `sales_rep_signoff_at`/`planner_signoff_at`). `list_outstanding_signoffs` (`prejob_cards.py:220-253`) already surfaces these rows + timestamps — **the natural place to add age computation.** | `prejob_cards.sent_for_check_at`, `*_signoff_at` |
| `bay_ready_to_merge_stale` | 🟢 NEW ⚠️ **age-basis decision** | State derived by `compute_bay_merge_readiness` (`chassis.py:723-773`) but it carries **no "ready since" timestamp**. Needs a proxy: latest `panels_arrived_in_bay` event `created_at` (`production_job_bay_events`) or `assembly_assigned.event_date`. **See Decision D2.** | bay state + event timestamps |
| `awaiting_qa_stale` | 🟢 NEW | `status='awaiting_qa'` (`list_awaiting_qa`, `chassis.py:885-897`) but that query does **not** return the transition timestamp — derivation must additionally read the `moved_to_awaiting_qa` event `event_date`. | `status` + `moved_to_awaiting_qa.event_date` |

**Bottom line:** 1 fully backed, 1 nearly free, the rest new *standing* derivations over already-persisted data. No migration.

### A.2 Validators NOT yet surfaced visually (bonus candidates)
VIN write-once lock (`capture_vin`, `chassis.py:456-458`); planner-attestation VIN-swap rule (`record_body_attached`, `chassis.py:825-830`); `find_anchorless_chassis` (no UI surface today); `check_calc_status_backed` (Invariant 2); Body-Gap-pending gate (`prejob_cards.py:444-448`, already a boolean column `body_gap_pending`); forward-only commitment gate (`return_chassis_to_parking`, `chassis.py:922-926`); `_assert_revertible` floor-commitment guards (`planning.py:378-396`).

### A.3 Redundancy (consolidation opportunities — noted, not fixed)
1. **⚠️ "Chassis received" is computed 3 divergent ways** — `planning._chassis_received` (VCL-event-keyed, `planning.py:101-105`) vs `production_jobs.chassis_received` (status-keyed, `production_jobs.py:512-520`) vs the inlined KPI copy. They **diverge on edge cases** (a chassis `in_assembly` with no VCL row reads received by one, not the other). **The ETA flags must pick one — see Decision D1.**
2. VIN format validated at 4 write paths — already well-consolidated through `ci.validate_vin_format` (good). The read-time legacy flag reuses `VIN_RE` directly.
3. `body_attached`-this-cycle existence is re-queried in 5 places; a shared `body_attached_on(chassis_id, cycle)` helper (`_latest_body_attached_dates` is the closest) is the natural consolidation point the bay flags should reuse.

---

## Part B — Visual-feedback reuse map

**Verdict: reuse-heavy.** Status-pill, tooltip, toast, and pulse infra all already exist and are house-styled.

| New primitive | Verdict | Reuse / extend | Key citations |
|---|---|---|---|
| `FlagBadge.tsx` | **Reuse** | Copy `StatusPill` wrapper (`ChassisList.tsx:26-32`); style map mirrors `CHASSIS_STATUS_STYLE` (`types.ts:86-94`). Tokens: **sky** `bg-sky-100 text-sky-700`, **amber** `bg-status-amber/15 text-status-amber`, **red** `bg-status-red/15 text-status-red`. Chrome `rounded-full px-2 py-0.5 text-[11px] font-semibold`. Always add neutral fallback (`DEFAULT_STATUS_STYLE` lesson, `statusPalette.tsx:27`). | `types.ts:86-103`, `ChassisList.tsx:26-42`, `tailwind.config.js:13-18` |
| `FlagPulse.tsx` | **Reuse (opt. 1-line config)** | Existing `animate-pulseRing` (cyan halo) is the app's "attention" pulse, already on unacknowledged Planning cards (`PlanningBoard.tsx:387,971`). For a **sky** pulse add one `pulseRingSky` keyframe next to it (`tailwind.config.js:24-50`); toggle via `pulsing ? 'animate-pulseRing' : ''` (`statusPalette.tsx:76`). NOT greenfield. | `tailwind.config.js:24-50`, `statusPalette.tsx:55-77` |
| `useSeenFlags.ts` | **Partial greenfield** | Copy try/catch + spread-merge shape from `useCockpitLayout.ts:22-59`; key `icb:seen-flags:{username}` (colon-namespace, per-user). Value JSON `{[flagId]: seenAtMs}`. **TTL prune (7d) + per-user keying is the new logic** — no existing key has TTL. | `AppDataContext.tsx:88-95,116-118`, `useCockpitLayout.ts:22-59` |
| Aggregate nav badge | **Mostly greenfield** | No numeric badge exists in TopNav; attach a count `<span>` to the right-side cluster (`TopNav.tsx:118`), red FlagBadge token. | `TopNav.tsx:40-69,118-143` |

**Tooltip decision:** the keyed `<Tooltip>` component is globally suppressible by the Tips toggle + sourced from `icb_tooltips.json` — **wrong fit** for flag tooltips (must show regardless of Tips; dynamic "flagged N days ago" text). Use a plain `title=` attribute (precedent `statusPalette.tsx:68-74`).

**Drop-gate refusal UX:** route 409s through `useToast().push({kind:'warn'|'error'})` / `handleApiError(e, toast.push)` (`AppDataContext.tsx:147`). Confirm dialogs reuse `Modal` (`overlays.tsx`).

**Two house lessons to carry into the new primitives:** (1) every style-map lookup has a neutral fallback for unknown keys; (2) every localStorage access is try/catch with a non-fatal swallow.

---

## Part C — Drop-gate audit + silent-deferral sweep

### C.1 Existing drop-gates — **NO client-only gaps (security verdict: clean)**
Every refusal in the §1 catalog has authoritative **server** enforcement; the frontend `draggable`/state suppressions are UX affordances on top of server chokepoints. A crafted POST hits the same raise.

| Gate | Server chokepoint (file:line) | Client affordance |
|---|---|---|
| Chassis→V/P slot, no ETA | `planning.schedule`→`eta_gate_reason` 422 (`planning.py:298,108-129`) | `PlanningBoard.tsx:867` |
| Occupied cell | `CellOccupiedError` 409 (`planning.py:310`) | `PlanningBoard.tsx:882` (409 flash) |
| Panels→bay (busy / double-link) | `record_panels_arrived_in_bay` 409 (`chassis.py:978-990`) | catches 409 (`BayModelLanes.tsx:239`) |
| body_attached (pre-conditions) | `record_body_attached` 422/409 (`chassis.py:804-830`) | merge btn gated on `ready_to_merge` (`:602`) |
| Bay tile→Awaiting QA, no body | `record_moved_to_awaiting_qa` 422 (`chassis.py:869`) | `isQaDraggable` (`:509`) |
| Bay tile→Parking, body exists | `return_chassis_to_parking` 409 (`chassis.py:922`) | `isParkingDraggable` (`:512`) |

### C.2 The 2 NEW v4.36b gates — **zero existing enforcement (both genuinely new)**
- **NEW Gate 1 — chassis→bay when incomplete.** `assign_assembly_bay` (`chassis.py:527-577`) loads the chassis but **never inspects `vin` or `customer_name`**. Router passes straight through. Genuinely new behaviour. ⚠️ **needs a predicate decision — see Decision D3.**
- **NEW Gate 2 — Pre-Job Sent when customer email NULL.** The data exists — `customers.email VARCHAR(300)` (`database.py:329`) — but **nothing in the prejob flow reads it.** `submit_for_check` gates only on sales rep / planner / Body Gap (`prejob_cards.py:440-448`); `build_email` ships blank recipients by design (`:530`). New gate; data is available to enforce it via `calc.customer_id → Customer.email`.

### C.3 Silent-deferral sweep (per §0.15 — surfaced, NOT fixed)

| Rank | file:line | Guard | Skips | Class |
|---|---|---|---|---|
| **1 (HIGH)** | `production_jobs.py:264-266` | `_auto_create_chassis_at_ack` `if not make: return` | Anchoring a chassis stub at **Planning ack** when no model entered | ⚠️ **The un-reversed sibling of the v4.36a.4 defect.** v4.36a.4 deleted the identical guard from the *pre-job* side (`_auto_create_chassis`) but left this *ack* twin intact ("graceful no-op"). A no-make ack silently anchors **no chassis** — same correct-but-silent UX defect, symmetric fix available (`create_expected_chassis` already accepts `make=None`). |
| 2 (LOW, mitigated) | `prejob_cards.py:418-419` | `_ensure_anchor_job` `if branch_id is None: return` | Creating the anchor job (confirmed card invisible to Planning) | Mitigated — `assert_confirmed_card_anchored` hard-fails the same txn (`prejob_cards.py:607-608`). Verify failure mode. |
| 3 (LOW, benign) | `prejob_cards.py:287-294` | `create_card` blank-make soft-fallback | Leaves draft make blank | Benign now that submit anchors a stub unconditionally (v4.36a.4). Cosmetic. |

All other early-return guards audited (≈20 sites across chassis/prejob/production_jobs/chassis_integrity/planning/chassis_merge) classified **legitimate** (pure read/format helpers, idempotency keys, documented NULL-exempt contracts).

**Recommendation:** Finding #1 is a real defect of the same class v4.36a.4 fixed. Per §0.15 + §9 carry-forward, it warrants a **separate small fast-follow WO** (symmetric ~1-2h fix) — NOT folded into v4.36b mid-sprint. Surfaced for BA sequencing.

---

## Decisions surfaced for BA (before §0 final lock)

- **D1 — "chassis received" definition for the ETA flags.** Three divergent implementations exist (A.3 #1). **Recommend: reuse `production_jobs.chassis_received()`** (status-keyed) so `job_eta_overdue` stays consistent with the existing `chassis_slipped` KPI it derives from. (The planning VCL-event variant would make the flag disagree with the KPI on `in_assembly`-no-VCL rows.)
- **D2 — `bay_ready_to_merge_stale` age basis.** No "ready since" timestamp exists. **Recommend: the latest `panels_arrived_in_bay` event `created_at`** (the moment the bay became merge-ready is when panels landed against an already-present chassis). Alternative: `assembly_assigned.event_date`. BA to confirm.
- **D3 — NEW Gate 1 "incomplete" predicate.** **Recommend: refuse `assign_assembly_bay` when `vin IS NULL OR customer_name` blank.** Note `assign_assembly_bay` already requires an open VCL cycle (chassis received), so by that point a VIN should normally exist — the gate catches the genuinely-incomplete case. BA to confirm predicate.
- **D4 — Pulse colour.** Existing pulse is cyan (`#06B6D4`). Spec says "sky pulse." **Recommend: add one `pulseRingSky` keyframe** (sky-500) to match FlagBadge's sky family. Trivial config add.

## Performance (§0.10 — 200ms p95): **achievable without materialization — confidence HIGH**
`compute_planning_board_flags()` is an aggregate over chassis + jobs + bays. The risk is N+1 per-item event reads (body_attached, moved_to_awaiting_qa dates). Mitigation: **batch-load events once per request** and derive in memory — `_latest_body_attached_dates` (`chassis.py:675-687`) already demonstrates the batched pattern. At demo-data scale (dozens of records) 200ms p95 is comfortable. Recommend an early perf smoke in §3.6 to lock it in before frontend builds on top. No denormalized columns (§0.10 honoured).

## Flag catalog vs validator coverage (§5 concern): **matches — implementable as specced**
Every §1 flag is backed by an existing rule/field or a pure read-only derivation over already-persisted data. No new business rules (§0.1 holds), no new tables (§0.2 holds). The only open items are the 4 decisions above (definitions/age-basis), not coverage gaps.

---

## Inputs
Subagent A (validators, 15 tool-uses) · Subagent B (visual patterns, 25) · Subagent C (gates + sweep, 23). Full agent transcripts retained in session.
