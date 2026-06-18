# ADR 0026 — Chassis data integrity across every write path (v4.36a)

- Status: Accepted
- Date: 2026-06-17
- Work Order: v4.36a — Chassis Integrity Sprint (Phase 1 of the v4.36 trilogy; Burt demo 23-24 Jun)
- Builds on: ADR 0015 (chassis-record lifecycle), ADR 0021 (chassis pipeline + job-number strategy),
  ADR 0023 (integrity invariants + Tier-2 guards), ADR 0024 (chokepoint + pattern-reuse), ADR 0025
  (event-derived body_attached + the demo-reset discipline).

## Context

By v4.35 the MES captured a chassis through three independent UI doors — the Pre-Job card (PJ), the
Planning acknowledgement (AJ), and the Add-Chassis "+New" modal (AC) — plus a late VIN-capture path on the
Chassis page. Each validated (or didn't) on its own terms. Michael's click-arounds produced the canonical
failure: a chassis carrying a typed but malformed VIN and a free-text `job_number` that pointed at no real
job — the "MICKEYTEST-class orphan." It looked linked, merged nowhere, and stranded the floor.

v4.36a is a single-concern sprint: **make chassis data correct-by-construction at every entry point**, so
that class of orphan cannot be created and the existing ones can be recovered. Nineteen §0 locks framed
it; five user-ratified decisions anchored it (strict 17-char VIN; auto-adopt with an explicit modal;
VIN write-once + admin-Merge for corrections; RED visual integrity deferred to v4.36b; a delete-orphan
admin surface + cleanup script). §3.0 discovery (a parallel-subagent Workflow → committed synthesis)
re-specced several premises against the real code — see the footnote ledger.

The engagement also produced an unusually dense methodology record: every sub-step ran discovery →
implement → adversarial-verify → live-verify → CI, and each surfaced a reusable pattern. Those are
consolidated below as the v4.36a pattern ledger (the depth peer of ADR 0021's).

## Decisions

1. **One definition of "valid chassis," one library (`chassis_integrity`, §0.13).** A single service —
   `VIN_RE = ^[A-HJ-NPR-Z0-9]{17}$`, `normalize_vin`, `validate_vin_format`, `validate_vin_uniqueness`,
   `validate_job_link`, `validate_dealer`, `validate_customer_consistency`, `resolve_existing_chassis`,
   and the `ChassisIntegrityError(ServiceError, status_code=422|409)` domain error mapped by a global
   `@app.exception_handler`. Every chassis-mutating path calls in here; no per-door validation logic.

2. **Strict VIN, write-time-only, NULL-exempt — enforced at the INTERACTIVE write, never at downstream
   propagation (the "D-VIN" rule, footnotes B1-B3).** A freshly-typed VIN is validated where it is typed
   (the PJ card edit, the AJ ack, the AC create, and — added in §3.8 — the 4th path, `capture_vin`). A
   *stored* legacy VIN is never re-validated: PJ→chassis propagation filters non-conformant values out
   (non-raising) rather than 422-ing an inherited row. All four write paths funnel through
   `validate_vin_format`; §3.8 closed the last drift (`capture_vin` had been strip+truncate).

3. **The job↔chassis link is atomic and guarded at EVERY door (closes MICKEYTEST; extends ADR 0024).**
   `create_chassis` sets `production_jobs.chassis_record_id` in the same transaction as the insert; the
   symmetric edit door (`update_chassis`, §3.5c) is link-aware — a LINKED chassis's FK + `job_number` are
   immutable (swap = admin Merge), an UNLINKED one links atomically from a dropdown. The free-text
   `job_number` is no longer a link surface; the authoritative link is the FK only.

4. **VIN-match adopts, never duplicates (§0.8).** A typed VIN matching a LIVE chassis links the selected
   job to it and returns a `ChassisCreateResult{chassis, adopted, message}` envelope (the frontend raises
   an explicit adoption modal). 409 is reserved for genuine conflict (job already has a different chassis,
   customer mismatch).

5. **Merge = re-point + soft-delete, never hard-delete (§3.6).** Admin Merge re-points the three FKs that
   reference the loser (`production_jobs`, `prejob_cards`, `chassis_lifecycle_events`; photos ride the
   event FK), renumbers colliding lifecycle cycles above the winner's max, then soft-deletes the loser
   (`deleted_at` + `merged_into_id`). It runs under a `with_for_update` row-lock (footnote R-lock), wraps
   the mutation in `IntegrityError→409` (footnote E-409), flattens prior tombstone chains (A→B then B→C ⇒
   A→C), and refuses two on-bay chassis (footnote double-bay). `restore` reverses it without auto-re-pointing
   (operator judgment). The loser stays navigable by id (a self-explaining tombstone banner).

6. **A `deleted_at IS NULL` safety floor (§3.6 STEP 1).** `list_chassis` + `find_anchorless_chassis` filter
   tombstones; `get_detail` deliberately does not (direct-nav). Landed BEFORE any soft-delete write path.

7. **Storage marker = the `merged_into_id` column, NOT a `status` sentinel (migration 0025; footnote
   schema-1).** `deleted_at` + `merged_into_id` are orthogonal to `status`, so the ~6 status-equality reads
   are never poisoned. (The BA's `status='merged_into:{id}'` pre-clarification was withdrawn after CA
   surfaced the hazard against in-flight code — footnote cultural-2.)

8. **Find Orphan is WIDE; the Inv3 health-check stays NARROW — one parameterized predicate (footnote
   recovery-orphan).** `find_anchorless_chassis(statuses=…)`: default narrow (the `expected` pipeline scope
   for `reconcile`/health), `statuses=None` wide (any status — catches the `received`-status MICKEYTEST
   class). Merged losers are excluded by category, not surfaced as accidental orphans.

9. **Delivery ETA reuses `production_jobs.chassis_eta` — no new column (§3.5e; footnote schema-2).** The
   ETA is job-owned (set at Planning Ack). The chassis modal pops `chassis_eta` from its payload and
   delegates to `_stamp_job_eta`, writing the linked job — one source of truth, no drift.

## Consequences

The MICKEYTEST-class orphan is unconstructable: no door accepts a malformed VIN, and `job_number` is no
longer a link surface. Existing orphans are findable + recoverable (retrofit-link / merge / soft-delete /
restore) by admins, with a Tier-2 cleanup script for production. Adversarial probes (§3.8, 3 subagents)
confirmed the surface holds under concurrency, edge VINs, and workflow edges, fixing two silent-corruption
breaks pre-commit. Deferred to v4.36b: RED visual integrity (the §0 lock), an operator-settable `status`
allowlist on `update_chassis`, a partial UNIQUE index on `production_jobs.chassis_record_id`, and a
dedicated chassis-audit table.

## Footnotes — the v4.36a pattern ledger

### A. Discipline patterns
- **A1 · Discovery-as-bug-catcher.** §3.0 mini-discovery is not ceremony: the §3.5e discovery found
  `chassis_records.chassis_eta` doesn't exist (the field is job-owned) before a wrong migration shipped;
  the §3.5d discovery found `update_card` skipped the token substitution `create_card` does.
- **A2 · Live-verification complements discovery; neither alone suffices.** Discovery catches structural
  gaps from reading; live verification catches sequencing/state gaps only visible when exercising the path
  with real data — e.g. the stale `card.template_id` (§3.5d) surfaced only on a live template switch even
  with perfect signature parity. Every §3.0-confirmed reuse is live-verified before commit.
- **A3 · §3.0 discovery must verify primitives behave EQUIVALENTLY across reuse contexts, not just
  signature-match.** The CREATE/UPDATE substitution divergence (§3.5e) is canonical: same function shape,
  different downstream behaviour.
- **A4 · Adversarial review DURING patch development, not only at the formal §3.8 stage.** Any write-path
  change is probed "what's the destructive null/clear/empty variant?" before commit — caught the
  clear-Customer-on-linked bypass (§3.5c) and the two merge breaks (§3.6) and the two §3.8 breaks.
- **A5 · The fixture sweep, three times over.** Tightening a validation must sweep EVERY test that fed the
  loosened path — and the sweep grep must NOT exclude `tests/journeys/` (the §3.8 miss: the unit test was
  swept, the late-VIN-entry journey was not, costing a CI round).
- **A6 · When the execution environment is unavailable mid-checkpoint, report state explicitly as
  "written / verified-pending" — never imply unrun work passed.**

### B. Integrity rules
- **B1 · Format at the interactive write, not downstream propagation (D-VIN).** See Decision 2.
- **B2 · Write-once VIN with a transitional-legacy carve-out.** A *conforming* captured VIN is read-only
  (correct via admin Merge — §0.3); a *legacy non-conforming* VIN stays editable so it can be corrected
  (locking it would dead-end — uneditable yet un-submittable). Applies to a create input; a stored VIN is
  corrected via Merge, not inline.
- **B3 · Single-definition-of-valid across all four write paths** (create / update / PJ-propagation /
  capture_vin). Per-entry-point drift is the hazard §3.8 closed.
- **B4 · Customer-consistency (§0.9), including the blank-clear.** A customer edit must stay consistent
  with the linked job; clearing it on a linked chassis is a 409 (it would silently wipe a name the job
  still asserts), not a short-circuit.

### C. Recovery patterns
- **C1 · Incremental least-destructive-first sequence.** §3.6 built in 7 steps (safety-floor → read-only
  orphan list → retrofit-link → soft-delete → merge-preview → merge → restore); each independently
  verifiable, halt at the latest verified state — never a destructive-but-unfinished surface.
- **C2 · Shared preview/apply kernel.** `renumber_plan` is called by both `preview_merge` and
  `merge_chassis`, so "what was previewed" == "what is applied" by construction. Any dry-run/commit pair
  shares the decision kernel, differing only in whether it writes.
- **C3 · Chain-flatten on merge.** Re-point prior tombstones (`merged_into_id == loser` → winner) so the
  audit pointer always resolves to a live survivor (single-hop), keeping restore tractable.
- **C4 · Restore does NOT auto-re-point.** The winner now owns the FKs; the operator re-links explicitly —
  reversal requires judgment, not a silent un-merge.
- **C5 · Tombstones self-explain + are read-only.** The detail banner distinguishes "merged into ‹VIN›"
  from "soft-deleted"; mutating actions are hidden on a tombstone (self-protecting UI).
- **C6 · History → must-merge ontology.** Junk soft-delete is gated on "no lifecycle history"; a chassis
  WITH history must be merged (history preserved), structurally steering the admin to the audit-preserving
  choice.
- **C7 · A merged loser is excluded from Find Orphan** (deliberately deprecated ≠ accidental orphan).

### D. Error / UX patterns
- **D1 · 422 vs 409 split.** 422 = bad input / failed precondition (format, unknown job/dealer); 409 =
  conflict with existing state (VIN clash, customer mismatch, job-taken, double-bay). Idempotent re-posts
  resolve to 409, not a 500.
- **D2 · Self-navigating remediation text.** Errors name the affordance that fixes them ("Use admin Merge
  Chassis", "Use Capture VIN") — the admin builds a mental map of the recovery surface from the errors.
- **D3 · Blocking vs warnings, never mixed.** A preview flag is either `blocking` (system enforces;
  admin cannot override — self-merge, deleted side, double-bay) or a `warning` (system surfaces; admin
  judges — VIN/customer/make difference, large event-delta).
- **D4 · Adopt an unambiguous related value during recovery when one source is blank.** retrofit-link
  fills a blank orphan customer from the job (reduces friction); only a non-null *conflict* 409s.
- **D5 · Decouple UX from storage AT THE SERVICE LAYER.** The chassis modal accepts `chassis_eta`; the
  service pops it and routes the write to `production_jobs` via `_stamp_job_eta`. The UX surface is the
  single entry point; storage routing is internal.
- **D6 · A correct-but-silent guard is a UX defect** (carried from v4.35 FIND footnote J): when the
  backend correctly refuses but the UI shows nothing, surface it.

### E. Concurrency / reuse patterns
- **E-lock · Row-lock precedent reuse.** Concurrent-merge protection reuses `record_planning_ack`'s exact
  idiom — `with_for_update`, id-ordered (deadlock-safe), then re-read so the guards re-check committed
  state. This is the engagement's canonical concurrent-mutation defence; new write paths reuse it rather
  than inventing.
- **E-409 · `IntegrityError → 409` translation.** Every write chokepoint wraps its commit in
  `try/except IntegrityError: rollback + raise ChassisIntegrityError(409)` so a constraint trip is a
  domain 4xx, never a raw 500 leaking DB internals.
- **E-reuse · Precedent-reuse over invention (four instances in v4.36a).** Concurrent-mutation row lock,
  chokepoint service composition, FK re-pointing in merge, and ETA-stamping (`_stamp_job_eta` mirrors
  `record_planning_ack`) all reused existing mechanisms — invention was the rare exception.

### F. Cultural patterns
- **F1 · CI honesty.** Failures are reported with the output and root-caused (the §3.8 capture-VIN reds
  were surfaced as "not a feature defect — a fixture sweep" with the failing assertion, not hidden).
- **F2 · Dual review catches errors in BOTH directions.** CA must surface a BA spec error with technical
  reasoning when it contradicts in-flight code or a §3.0 ratification — not silently comply (the
  `status='merged_into:{id}'` withdrawal; the `chassis_eta`-column-doesn't-exist gate).
- **F3 · Tier-2 discipline holds under inconvenience.** When the auto-mode classifier blocked a raw-SQL
  verification on the shared dev DB, the response was to defer the assertion to an `icb_test` journey —
  not to bypass. The v4.34.4 lockdown is a discipline, not an obstacle.
- **F4 · No silent caps / scope creep.** Out-of-scope finds are surfaced to the BA for a separate WO, not
  folded in; deferred items are logged explicitly (status allowlist, FK unique index, audit table).

### G. Schema / architecture
- **G1 · `deleted_at` + `merged_into_id` columns over a `status` sentinel** (Decision 7).
- **G2 · ETA reuses `production_jobs.chassis_eta` — no second column** (Decision 9).
- **G3 · A parameterized shared predicate** serves a narrow (health-check) and a wide (admin) scope
  without duplication (Decision 8).
- **G4 · No DB UNIQUE on `production_jobs.chassis_record_id` is the multi-cycle reality.** A chassis
  legitimately runs through multiple jobs over its life; merge consolidates jobs onto the winner without
  violating any unique (`calculation_record_id`'s 1:1 unique is untouched by the FK re-point).
- **G5 · Forward-looking soft-delete-on-referencer flag.** When soft-delete is introduced on a referenced
  table, the refuse-if-live-FK guards on referencers must be revisited if those referencers ever gain
  their own `deleted_at` (today only `chassis_records` has one, so existence == liveness for the guards).

### H. State-promotion patterns (WO v4.36a.1 — Awaiting-QA handoff)
- **H1 · Phase-only-refines vs status-promotes-transitions.** A lifecycle EVENT is one of two kinds, and the
  kind decides whether it touches `chassis_records.status`. `body_attached` (v4.35) is **phase-only**: it
  refines the *current* phase (the chassis is still in assembly), so status stays `in_assembly` and the event
  alone carries the meaning. `moved_to_awaiting_qa` (v4.36a.1) is a **phase transition**: the chassis has
  *left* assembly for the QA queue, so the event AND `status='awaiting_qa'` are written in one transaction.
  The test is "did the chassis change which phase it is in?" — if no, event-only; if yes, event + status.
- **H2 · Status-promoting events require a grep-style audit of every read that gates on the PRIOR status.**
  When a new status value transitions out of an existing one, audit every `WHERE status = '<old>'` read and
  decide, per read, whether the new status should be **INCLUDED** (a downstream consumer that *inherits* from
  the old phase) or **EXCLUDED** (a sibling-phase consumer). The semantic question per read is whether that
  consumer cares about "inherits-or-not" from the prior status. In v4.36a.1 the sweep of `in_assembly` reads
  found all bay-occupancy reads correctly EXCLUDE `awaiting_qa` for free (they ask "on a bay *now*?"), while
  exactly one — `chassis_received()` ("booked-in / on-site?") — had to INCLUDE it, because Awaiting-QA is
  unambiguously past the booked-in line. This per-read INCLUDE/EXCLUDE triage is the transferable discipline
  for the v4.36c status-promotion work (`in_qc`, `qc_complete`, `dispatched`); a denormalised status is cheap
  to *write* but every prior-status read is a latent place to get the new value's membership wrong.
- **H3 · A reverse transition is the inverse of its forward write — DELETE the event, don't add one (WO
  v4.36a.2 return-to-parking).** Moving a chassis back from a bay to Parking is the exact inverse of
  `assign_assembly_bay`: it DELETEs the cycle's `assembly_assigned` event and flips `status` back to
  `in_workshop` (mirroring the panels move-back undo `clear_panels_arrived`). Deleting the event — rather
  than writing a new "unassigned" event — keeps all six `assembly_assigned` consumers (occupancy, bay
  derivation, KPIs) working UNCHANGED; a reversing event would force every one of them to learn the new
  type. Audit lives separately (a `production_jobs_audit` row, reuse of the v4.34.2 unschedule trail), so
  current-state stays clean while the decision is still recorded.
- **H4 · Reversibility is gated on the commitment point.** When designing reversibility in a workflow
  state machine, identify the **commitment point** — the transition where reversal becomes destructive —
  and gate reverse operations on it. `body_attached` is the chassis-cycle commitment gate: reverse *before*
  it (return to Parking) preserves bay-clearing flexibility for re-prioritisation; reverse *after* it
  requires forward progression (to Awaiting QA, **not** back to Parking — the panels are merged to the
  body). The same `_has_event(body_attached)` check that the merge guard uses becomes the *return* guard —
  one event, read by both the forward and the reverse path, keeps the dual-direction state machine's gates
  consistent (forward → QA after the gate, reverse → Parking only before it).
