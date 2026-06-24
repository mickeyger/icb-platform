# Visual-Integrity Drop-Gate Catalog (WO v4.36b §3.4)

> The canonical inventory of every planning-board / workflow **drop-gate** — a server-enforced refusal
> that stops an invalid state transition, surfaced to the operator with a remediation message. Future
> sprints append here (the §9 carry-forward discipline).
>
> **Pattern:** every gate is enforced **server-side** (the authoritative chokepoint) — the frontend
> `draggable`/disabled affordances are UX sugar on top; a crafted request hits the same raise. Refusals
> reuse the existing HTTP semantics: **409** (conflict / state precludes the action — the frontend
> catches it inline or re-throws to a modal) or **422** (precondition not met → toast). No new HTTP codes.

## Existing gates (verified in §3.0 Subagent C audit — all server-enforced, no client-only gaps)

| Gate | Predicate (refuse when…) | Server chokepoint | Status · message |
|---|---|---|---|
| Chassis → V/P slot, no ETA | chassis not received AND no ETA (or ETA after target week) | `planning.schedule`/`move` → `eta_gate_reason` (`planning.py:108-129`) | 422 · "capture a chassis ETA or mark the chassis received before scheduling" |
| Drop onto occupied cell | target slot already occupied | `planning.schedule` (`planning.py:310`) | 409 · "slot {bay} in week {iso} is already occupied" |
| Panels → bay (busy / wrong) | bay already holds another job's panels | `record_panels_arrived_in_bay` (`chassis.py:984-990`) | 409 · "{bay} already holds panels for another job" |
| Trigger `body_attached` | chassis not on a bay / wrong status / already attached / VIN-attestation mismatch | `record_body_attached` (`chassis.py:804-830`) | 422/409 · "assign it to a bay first" / "body already attached" / planner-attestation VIN clash |
| Bay tile → Awaiting QA | no `body_attached` event this cycle | `record_moved_to_awaiting_qa` (`chassis.py:869`) | 422 · "attach the body first — only a body-attached chassis can move to Awaiting QA" |
| Bay tile → Parking | a `body_attached` event exists (post-merge) | `return_chassis_to_parking` (`chassis.py:922`) | 409 · "body already attached — it can't go back to parking; move it forward to Awaiting QA" |
| Move panels back (consumed) | panels consumed by a `body_attached` | `clear_panels_arrived` (`chassis.py:1012-1016`) | 409 · "panels are part of a merged body" |
| Revert / unschedule | job committed to the floor (panels staged / body attached / WO started / QC) | `planning._assert_revertible` (`planning.py:347-396`) | 409 · `RevertNotAllowedError` |

## NEW v4.36b gates

### Gate 1 — incomplete chassis → assembly bay  (D3)
**Chokepoint:** `services.chassis.assign_assembly_bay` (`chassis.py:527`).
**Refusal:** 409 (the existing bay-drop pattern — `BayModelLanes` catches 409 → inline reject flash).

| Dimension | Predicate | Status (this PR) |
|---|---|---|
| **VIN** | `vin` is null/blank | ✅ **SHIPPED** — refuse: *"Chassis has no VIN — capture it on the Chassis page before assigning a bay"* |
| **Customer** | (D3 literal) `customer_name` blank | ⏸ **HELD pending BA re-ratification** — see ⚠️ below |

> ⚠️ **Customer-dimension conflict (data-backed).** Literal D3 (`customer_name blank`) refuses **8 of 9**
> booked-in chassis on canonical icb: they all carry a VIN but `customer_name` is NULL because the
> customer is denormalised **onto the linked job, not the chassis row** (the same gap the
> `chassis_no_customer` flag surfaces). It also breaks the assign API tests (their `fresh_chassis` fixture
> is customerless + jobless). **Recommended re-aim:** refuse only when **no customer is resolvable
> anywhere** — `chassis.customer_name` blank **AND** the linked job has no customer (`_job_customer_name`).
> On icb this refuses **0** of the 9 (all have a job-customer) yet still catches a genuinely customerless
> chassis. Requires adding `customer_name` to ~3 assign-test fixtures. Awaiting BA ratification before
> landing the customer dimension.

### Gate 2 — Pre-Job send when customer email missing  (§1)
**Status:** ⏸ **HELD — premise conflict surfaced.**

> ⚠️ The §1 premise is "the Pre-Job Card is **delivered to the customer**, so refuse when
> `customers.email` is null." In code the Pre-Job Card email (`prejob_cards.build_email`, the only
> pre-job email path, via `GET /api/prejob-cards/{id}/email`) is an **internal sign-off notification** —
> its body literally states *"Sent from ICB MES (internal document — not for the customer)"*, the
> recipients are deliberately blank, and the links are sales-rep / planner **sign-off** links. There is
> **no customer-delivery action** in the pre-job flow to gate. Gating `submit_for_check` on
> `customers.email` would refuse a valid internal workflow for an irrelevant reason (and many seed
> customers carry no email).
>
> **Recommended re-aim:** convert Gate 2 from a hard send-gate to a **visual-integrity flag**
> (`job_customer_no_email` — surfaced on the Health Check dashboard + the costing/job rows), consistent
> with the sprint theme (surface, don't block) — OR drop it if customer email isn't a tracked concern
> yet. Awaiting BA decision.

## Audit-log note
Gate refusals are stateless (no row written) — they raise before any mutation, so there is nothing to
audit. (Contrast the v4.36a.2 `return_chassis_to_parking`, which DOES write a `ProductionJobAudit` row
because it performs a state change.)
