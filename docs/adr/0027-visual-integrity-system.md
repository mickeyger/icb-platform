# ADR 0027 — Visual Integrity System: derived flags, drop-gate catalog, Health Check (v4.36b)

- Status: Accepted
- Date: 2026-06-24
- Work Order: v4.36b — Visual Integrity System (Phase 2 of the v4.36 trilogy; Week 1 of Phase 1, ship 28 Jun)
- Builds on: ADR 0026 (chassis data integrity — the validators these flags surface), ADR 0023 (integrity
  invariants + Tier-2 demo-reset discipline), ADR 0024 (chokepoint + pattern-reuse), ADR 0025
  (event-derived state + demo-readiness), ADR 0018 (bay model).

## Context

v4.36a made chassis data correct-by-construction at every write door. But correctness the system *enforces*
is invisible to the owner walking the floor: a chassis stuck without a VIN, an ETA gone overdue, a bay
ready-to-merge for two days — each is knowable from existing data, none was *surfaced*. v4.36b builds the
**Visual Integrity System**: Burt opens the MES and the screen tells him what needs his eyes. Three parts —
**RED/amber/sky flag rendering** on the existing surfaces, a **drop-gate catalog** (every workflow refusal,
documented + server-enforced), and a **Health Check admin dashboard** he lands on from a nav badge.

The single concern (§0.1): **flags DERIVE from existing validators/data — no new business rules.** The lock
that shaped every decision (§0.2): **no new tables, columns, or migrations** — flags are computed at request
time. The sprint ran in parallel with CA4's v4.38 Feedback Portal on the shared repo + `icb` DB, so a second
through-line was **lane separation** — every architectural choice below also happens to be the one that kept
the two lanes from colliding. Twenty §0 locks framed it; ratified decisions D1-D4 anchored the flag
semantics. §3.0 discovery (3 parallel subagents → committed synthesis,
`docs/audit/v4_36b_S3_0_visual_integrity_discovery.md`) re-specced several premises against the real code —
see the footnote ledger.

## Decisions

1. **Visual integrity is DERIVED rendering, not new state (§0.1/§0.2).** One read-only service
   (`services/visual_integrity.py`) computes every flag at request time from already-persisted data —
   `compute_{chassis,job,bay}_flags`, `compute_planning_board_flags` (aggregate), `list_flagged_*`
   (drill-through) — behind four `GET /api/visual-integrity/flags/*` endpoints. **Zero new tables/columns;
   zero migrations.** Each of the 13 catalog flags traces to an existing validator or field (the §3.0
   coverage map). Severity is resolved server-side from a per-flag `FlagSpec.bands` table (the §0.6 ageing
   ramp, with explicit per-flag overrides); the frontend renders the resolved value. The §1 "received"
   ambiguity (three divergent definitions in the codebase) was resolved by **reusing
   `production_jobs.chassis_received()`** (D1) so the ETA flags never disagree with the `chassis_slipped`
   KPI they derive from.

2. **Per-consumer hooks, not a shared provider (§3.2).** Each surface fetches only its slice
   (`useFlagSummary` for the nav badge, `useFlaggedChassis/Jobs/Bays` maps for rows/tiles) — there is **no
   shared flag context in `Layout.tsx`**. This kept the new primitives (`FlagBadge`, `FlagPulse`,
   `AgeingPill`, `useSeenFlags`) thin extensions of existing house patterns (`StatusPill`, `animate-pulseRing`)
   and — the load-bearing benefit — meant **zero contention with CA4**, who mounts `FeedbackWidget` in
   `Layout.tsx`. *When to reuse vs. a shared provider:* prefer per-consumer hooks when surfaces need
   different slices and lanes are parallel; a shared provider earns its place only when many consumers need
   the *same* live-updating slice and cache coherence across them matters.

3. **Reuse the existing dispatcher; don't edit the route table (§3.3).** The Health Check screen registered
   via the existing dynamic `/admin/:resource` route + `CUSTOM_ADMIN_SCREENS` + `ADMIN_RESOURCES` — **no
   `App.tsx` edit**. This both avoided a route-table merge against CA4's `/admin/feedback` and followed the
   standing precedent-reuse rule: find the registry, add an entry, don't grow the wiring.

4. **Role visibility is a service-layer filter, not permission keys (§3.5 / §0.11).** The §0.11 matrix
   (admin/planner/production → all; workshop → Jobs+Bays; sales → Chassis+Sign-offs+Stale-Reviews) is a
   **module-level `_ROLE_GROUPS` constant** filtering the returned flags by group; the endpoints pass the
   session role through. Real `flag.read.*` permission keys would have meant a new permissions **migration**
   — which would collide with CA4's already-held alembic 0027 (Decision 6). The role-filter needs no
   migration, continues the §3.1 `require_user` convention (this codebase has no `.read` keys — the §0.4
   deviation, BA-ratified at §3.1), and keeps UI-hide **automatic** (the backend returns only the role's
   flags + a role-filtered `/flags/catalog`, so a restricted role's dashboard cards don't render — no
   two-place gating to drift). *Phase 2+ path:* if admin-configurable matrices are ever needed, add a
   `flag_permissions` table then; until there is a consumer, the constant is correct.

5. **§3.0 discovery verifies the PREMISE, not just the predicate (§3.4).** NEW Gate 2 ("refuse Pre-Job
   send when the customer email is missing") was dropped — **not because the predicate was wrong, but
   because the premise didn't hold**: the only pre-job email is an internal sign-off notification
   (`build_email`, literally *"not for the customer"*) — there is no customer-delivery action to gate.
   Correspondingly Gate 1 was **re-aimed** (D3): literal `chassis.customer_name IS NULL` would have refused
   8 of 9 booked-in demo chassis (customer lives on the job by design), so the gate refuses only when **no
   customer is resolvable on the chassis OR its linked job**. Standing rule, now folded into §3.0: a
   discovery subagent verifies each proposed gate/flag's **premise against the real code path**, not only
   its predicate logic.

6. **Held-migration / same-chain coordination for multi-CA sprints (§3.5).** v4.36b deliberately adds **no
   migration** (the head stays at `0026_chassis_tail_lift_code`); CA4 owns the next number, 0027, for the
   feedback table. Any sprint touching role/permission/auth surfaces now runs a §3.0 pre-check — *"does this
   need a new migration, or can it ride existing convention?"* — and a shared-chain §0-lock names the owner
   of the next revision. This is the standing template for parallel-CA alembic-chain contention.

7. **Respect the guard; leave demo-intent undemoed (§3.7).** The curated demo reseed wanted to light all 13
   flags, but `chassis_no_production_job` **is** Invariant 3 (an anchorless `expected` chassis) — which the
   reseed's in-transaction `run_health_checks` gate refuses (rollback). The right answer was **not** to seed
   around the guard: the flag stays in the catalog as a real-data integrity surface (admin Find-Orphan
   recovery), shows a greyed "0" on the dashboard, and the owner click-through narrates *"this lights up if a
   genuinely orphaned chassis appears."* A guard refusing your demo data is the guard working.

## Footnote ledger — checkpoint catches (the methodology record)

- **A · §3.1 perf headroom.** The aggregate flag computation is **batched** (events loaded once per request,
  derived in memory — the `_latest_body_attached_dates` pattern), no N+1, no materialized columns:
  `compute_planning_board_flags` p95 **14.5ms** at §3.1, **9.9ms** after §3.2-§3.5 layered on (role-filtering
  *reduced* work on non-admin sessions) — **~20× under the 200ms §0.10 target.** Perf was pulled forward to
  §3.1 (validate before building on top) and sanity-checked at §3.6 (no drift).

- **B · §3.2 second day-counter (live-verify).** The AgeingPill swap (§3.7) revealed a **second** `day-counter`
  on the Planning board — the v4.36a.5 Pre-Assembly mockup — that `tsc` + build couldn't flag (both render).
  Caught only on live-verify; both were swapped so the board reads consistently. The human/live-verify
  discipline earns its place precisely on cosmetic-coherence misses the type system can't see.

- **C · §3.3 dispatch miss (self-caught).** The Health Check import was added but the
  `CUSTOM_ADMIN_SCREENS['health-check']` dispatch entry was initially forgotten → the route silently fell
  back to the templates screen (a classic silent-deferral: wrong screen, no error). Caught on the §3.3
  live-verify, not at compile — reinforcing live-verify at *every* checkpoint, not just §3.7.

- **D · §3.4 Gate 1 false-positive averted + Gate 2 premise.** Data (not intuition) caught Gate 1: literal D3
  would have refused **8/9** booked-in chassis. Re-aimed to "no resolvable customer anywhere" → refuses 0 of
  the 9, still catches a truly customerless one. Gate 2 dropped on premise (Decision 5). Both surfaced with
  the supporting query before any code landed.

- **E · §3.5 migration collision avoided.** `flag.read.*` permission keys would have needed a migration
  colliding with CA4's held 0027; the role-filter (Decision 4) sidesteps it entirely — the same
  surface-separation instinct as Decisions 2 and 3.

- **F · §3.7 invariant guard catching demo-intent.** Decision 7 — Invariant 3 refused `chassis_no_production_job`
  in the reseed; respected, not worked around.

## Consequences

- The owner gets a single glanceable surface (Health Check) + point-of-work badges, all from existing data —
  no new schema, no new write paths, nothing to keep in sync beyond the validators that already exist.
- v4.36b ships migration-free, frontend-additive (no `TopNav`/`Layout`/`App` structural edits beyond a nav
  badge), and `/calculator` byte-identical (§0.12) — clean to squash-merge alongside CA4's v4.38.
- **Carry-forward:** the silent-deferral sibling at `production_jobs.py:264` (the un-reversed v4.36a.4 twin,
  surfaced by the §3.0 Subagent-C sweep) → fast-follow **v4.36b.1**; CI flake stabilization → **v4.36b.3**
  (unblocks the Ubuntu-required branch-protection gate); `csrf_middleware` → **v4.36b.2**.
- The role matrix is a code constant; admin-configurable matrices are deferred to Phase 2+ behind a
  `flag_permissions` table (Decision 4). `awaiting_qa_stale` becomes Kenny's QC inbox source in v4.36c.
