# ADR 0022 — Pre-Job Card polish (v4.33.1) + Dealers, multi-contact & VIN late-entry (v4.34.1)

- Status: Accepted
- Date: 2026-06-14 (v4.33.1) · 2026-06-15 (v4.34.1 section appended)
- Work Order: v4.33.1 — Pre-Job Card Polish Bucket; **v4.34.1 — Dealers via Customer Flag +
  Multi-Contact + Gap A VIN late-entry** (folded in per the v4.33.1 note below)
- Note: a brief polish-bucket ADR (§0.12). The **v4.34.1 section is at the bottom** — folded in here
  as planned rather than minting ADR 0023, since 0022 was reserved for this follow-on.

## Context

v4.33 shipped the Pre-Job Card workflow (templates + 3-role sign-off + PDF + token engine + fridge
DDM). v4.33.1 polishes the rough edges Michael found in demo walkthroughs and completes deferred
follow-ups — none correctness-critical. The notable outcome is a **scope deletion**: §3.3 (fridge
mounting drawings B–H) was deferred after discovery showed the source data doesn't fit the spec.

## Decisions

1. **Admin "Outstanding Pre-Job Sign-offs" page (§3.1)** — a read-only nav-aid listing
   `sent_for_check` cards (the exact awaiting-sign-off set; reject returns a card to `draft`), with
   per-role status, age, filter chips, and deep-links to the existing sign-off pages. `require_admin`.
2. **Custom-admin dispatch map (§3.1)** — `AdminModule` now maps a `custom` resource key →
   component (`CUSTOM_ADMIN_SCREENS`), replacing the single hardcoded render. The documented
   extension point for future custom admin screens.
3. **Attestation modal = boilerplate + required checkbox + notes (§3.2)** — the sign-off modal
   mirrors the legacy PreJobSignoffModal: a fixed legal statement (signer + role + quote
   interpolated), a checkbox that gates the Sign-off button, and an optional notes box. The
   **persisted attestation is the boilerplate WITH notes appended** — the exact confirmed text is
   the audit record, not just the notes.
4. **Medical Waste template (§3.4)** — the 8th body class, seeded **from the Explosive base** (no
   Nadie doc) with "Explosive" → "Medical Waste" text swaps, `is_active=False` (DRAFT) so it stays
   out of the active-only selector until Nadie reviews + an admin approves. Count 22 → 23.
5. **Template-size soft warning (§3.5)** — a non-blocking amber banner when the costing length
   exceeds 2× the template's nominal length. Both values **derive from text** (template *name*
   nominal length; baked *section* dimensions) — no column, no migration. Unparseable → skip
   silently.
6. **Human-numeric template sort (§3.6)** — one shared `compareTemplatesBySize` comparator (size
   bucket: `2.3m < 3.2m < mid < big < 15.5m`, un-sized last), applied to the admin list + the
   Pre-Job selector. Fixes the lexical "15.5m before 2.3m".

## The fridge multi-mounting finding — §3.3 DEFERRED

§0.6 assumed the B/D/F/G/H drawings carry **cutout dimensions per mounting style**. Reading all five
PDFs showed otherwise — they are mounting-geometry references, several explicitly "No Cutout":

| Drawing | Type | Fridges present | Cutout W×H? |
|---|---|---|---|
| A (shipped v4.33) | Front-Mount cutout table | 30 models | ✅ the only cutout drawing |
| **B** — B Type Front | **No Cutout** | Transfrig R 500 TE, R 600 TE | ❌ mounting centres only |
| **D** — D Type Front | 6-column mounting table (SIZE A–F) | Transfrig ×2, Carrier Xarios ×6 + Viento, Thermoking ×3 groups, Tundra, TwisterTrans, Kooltube ×2 (~14) | ❌ mounting dims |
| **F** — F Type Front | **No Cutout**, 5-dim | Thermoking V200 max, V300 max | ❌ none |
| **G** — G Type Front | **No Cutout** | JAVGRO C170-DC | ❌ centres only |
| **H** — H Type | single drawing (2 centres) | Kooltube C7 | ❌ centres only |

`fridge_units.cutout_width_mm/height_mm` can only ever be NULL for B–H, and **no template token
consumes the mounting letter**, and **no current card workflow selects a mounting style**. Seeding
~20 cutout-less rows + widening `uq_fridge_units_manufacturer_model` to include `mounting_drawing`
would be schema + UI churn with no consumer — the **"don't fold an empty/data-less DDM"** rule
(ADR 0021 fn 34), applied a second time.

**DEFERRED-WO MARKER —** *"Multi-mounting fridge DDM + `(manufacturer, model, mounting_drawing)`
constraint widen + Pre-Job fridge-picker mounting surface."* **Blocked on a confirmed downstream
consumer** (likely v4.36+ workshop tablet, which would render the mounting geometry). The 5-PDF
inventory above is the source when it proceeds.

**Knock-on:** with §3.3 out, **v4.33.1 ships ZERO migrations** — freeing migration **0022** for
v4.34.1.

## Ledger — v4.33.1 lessons

1. **Spec-vs-data verification before building** — §0.6 assumed cutout-per-mounting; the PDFs proved
   it wrong. The §3.0 discipline applied mid-build saved a speculative schema change.
2. **Don't fold an empty/data-less DDM** (ADR 0021 fn 34, reapplied) — the discipline held a second
   time; the deferral is a decision, not an omission.
3. **Derive-from-text over schema columns** — §3.5/§3.6 derive from the template name, the baked
   sections, and `size_category`; v4.33.1 ships zero migrations as a result.
4. **Skip-silently soft warnings** — a non-blocking warning that can't parse its inputs skips (logs a
   one-liner), never false-positives.
5. **Audit-trail attestation** — store the confirmed boilerplate (with notes appended), not just the
   notes, so the exact attested text is the record.
6. **One comparator, two consumers** — the size-bucket sort lives in `lib/templateSort` and drives
   both the admin list and the modal selector (no drift).
7. **Custom-admin dispatch map** — a key→component map prevents a second custom resource rendering
   the first; the documented extension point.
8. **Draft-by-default for review artifacts** — the Medical Waste template seeds inactive so it can't
   leak into the active selector before Nadie's review.
9. **Incremental WO merges re-base off squashed main** — §3.1+§3.2 merged mid-WO (PR #26); the
   continuation branch was cut from the squash commit, not the merged feature tip, so the next PR
   shows only the new work.

## As-shipped (v4.33.1)

- Admin sidebar gains **"Pre-Job sign-offs"** (below "Fridge units"); the page lists `sent_for_check`
  cards with filters + row actions.
- The attestation modal is redesigned: boilerplate + required checkbox + optional notes; the stored
  attestation carries the boilerplate + notes.
- **Medical Waste** template imported as a **draft** (count 22 → 23) — Nadie must review the section
  copy + an admin approves to activate.
- Template-size mismatch warning shows for over-size selections (non-blocking).
- Template lists sort **human-numeric** (admin list + Pre-Job selector).
- **§3.3 deferred** (fridge B–H — no cutout data / no consumer); **zero migrations** shipped.
- 2 new per-role journey suites green (outstanding sign-offs + attestation modal); the existing
  sign-off + create + reject journeys stay green.
- **Coverage note:** §3.5 (size warning) + §3.6 (sort) are frontend logic CI can't journey-test
  (fresh DB has no templates; no frontend unit runner) — build-verified + exercised by the create
  journey's sorted modal.
- v4.31/v4.32/v4.33/v4.34 surfaces untouched; `/calculator` byte-identical; CI green both runners.

---

# v4.34.1 — Dealers via customer flag + multi-contact + Gap A VIN late-entry

- Status: Accepted · Date: 2026-06-15 · Work Order: v4.34.1

## Context

Michael surfaced a 28-line dealer list (`Dealers.txt`) and Nadie's reality that a customer has
several contacts. Investigation (v4.34 era) had found NO structured dealer source and that **Customer
is already a first-class FK** (`customers` + `calculations.customer_id`). The chassis pipeline (v4.34)
needed the *supplying dealer* captured at Planning ack. Two follow-ons rode along: multi-contact, and
**Gap A** — capturing a VIN that wasn't entered at the Pre-Job stage.

## Decisions

1. **Dealers are a FLAG, not a table (§0.2).** `customers.is_dealer` (bool). An entity can be BOTH a
   biller and a chassis supplier (Burt), so a separate `dealers` table would have forced a fake split
   and duplicate records. Pure dealers are `is_dealer=true` rows with nullable billing fields. This
   reversed the v4.34-era "Dealer DDM" plan once the both-roles reality was confirmed.
2. **`customer_contacts` + one-primary invariant (§0.6).** Multiple contacts per customer; a
   **partial unique index** `uq_customer_contacts_one_primary (customer_id) WHERE is_primary`
   enforces one primary in the DB (not app code). `set-primary` demotes-then-promotes with a flush
   between, because Postgres checks the partial-unique immediately (no DEFERRABLE on a partial index).
   Soft-delete via `is_active` keeps history.
3. **Deprecate-not-drop the legacy contact cache (§0.7, ADR 0016).** Migration 0022 backfilled
   `customers.email/telephone` into a primary `customer_contacts` row (2147 rows) but KEEPS the cache
   columns — existing read-paths (`/api/customers`) stay valid; the contact table is the new write path.
4. **Cross-schema `chassis_records.dealer_id` (§0.3, ADR 0006).** Plain `Integer` on the schema-less
   model; FK to `icb_costings.customers` created in migration 0022 (`SET NULL`), registered in
   `CROSS_SCHEMA_FKS` + indexed on the model so `alembic check` adds zero net-new drift. Propagated
   onto the linked chassis at Planning ack (mirrors v4.34's ack→chassis pattern).
5. **Same-entity render (§3.4).** When one `customers` row is both the body customer and the supplier,
   the Chassis list badges the Customer cell `customer + dealer` rather than repeating the name.
6. **Customers admin via the dispatch-map (§3.5).** The third `CUSTOM_ADMIN_SCREENS` entry (the
   v4.33.1 extension point, decision 2 above) — searchable server-side list over 2160 + a Contacts
   panel CRUD + an `is_dealer` toggle.
7. **Dealer seed = prefix-extraction + 4-step fuzzy match (§3.7).** `Dealers.txt` lines are
   `"<dealer> - <end customer>"`; the dealer is the prefix. De-dup collapses ITC Midrand ×3 + Ronnies
   ×2 → 25 unique. Match: exact → normalised → prefix (`<dealer>` ⊂ `<dealer> (Pty) Ltd`) → insert.
   14 exact, 4 prefix, 7 inserted. A committed `dealer_seed_decisions.csv` is the auditable record;
   the seed is idempotent + forward-only (never un-flags).

## Footnotes

8. **Gap A is the first backend NULL-state enforcement of sign-off integrity.** v4.34's VIN lock was
   frontend-only; §3.4b's `POST /api/chassis-records/{id}/vin` accepts a VIN ONLY when the current
   value is NULL (write-once NULL→value), stamping `vin_source='chassis_page_manual'`. *Sign-off
   integrity was frontend-only through v4.34; this NULL→value write-once guard is the first backend
   enforcement, pending full attest-and-lock hardening when Job-Card-generation lands (v4.36+).*
9. **Gap A is gated on `chassis.update` (planner + production + admin), not strict planner/admin
   (BA-ruled).** The spec said "planner/admin" before it was known production holds `chassis.update`;
   production legitimately reads the VIN off the plate at chassis arrival. The NULL-state guard makes
   the broader cluster safe — no one can overwrite a known VIN through this path.
10. **The v4.33 status-sync gap (hotfix PR #28).** The v4.33 Pre-Job Card flow advanced
    `production_jobs.status` but never `calculations.status`, which the Costings dashboard reads — so
    both-signed-off cards showed "Accepted" and never flowed to Planning. Fixed by mirroring the card
    lifecycle onto the calc (+ a forward-only backfill of 13 confirmed). Two lessons worth keeping:
    **(a) a fresh seed MASKED the bug** — the seed manufactures confirmed-card-on-accepted-job rows,
    so the inconsistency only showed after real transitions; **(b) state-machine bugs surface most
    clearly under state *transitions*, not at initial setup** (the v4.34 "instrument-to-diagnose
    corrects your hypothesis" pattern, ADR 0021, applied to a workflow gap).

## Deferred / flagged

- **3 pre-existing local `alembic check` FK drift items** (`fk_calculations_sales_rep_user`,
  `fk_chassis_events_assembly_bay`, `fk_prejob_cards_chassis_record`) — present at clean 0021,
  env-only-local (pass on CI), NOT introduced by 0022 → **v4.35 housekeeping bundle**.
- **2 jobless confirmed calcs** (`A9907`) show *Pre-Job Confirmed* but can't reach Planning (no
  production job — the "partial" accept state) → **v4.34.3 investigation** (likely a silent
  job-creation failure / partial-accept edge).

## Ledger — v4.34.1 lessons

1. **Flag-over-table when an entity plays two roles** — `is_dealer` avoided splitting Burt into a
   customer AND a dealer record.
2. **DB-enforced invariants over app guards** — the partial-unique index makes "one primary" a
   storage property, not a code convention; the flush-ordered swap is the only app concession.
3. **Deprecate-not-drop the cache** — the email/telephone columns stay readable while the contact
   table becomes the write path (ADR 0016 reapplied).
4. **Auditable seeds** — the fuzzy-match writes its decisions to CSV for human review before trust;
   prefix-extraction + consolidation are visible, not implicit.
5. **Backend NULL-state guards are cheap integrity** — a one-way NULL→value transition is the
   smallest possible write-once lock, and made the permission breadth a non-issue.

## As-shipped (v4.34.1)

- **Chassis** list gains a **Dealer** column (same-entity `customer + dealer` badge); detail gains a
  **Dealer** field, a **Capture VIN** pencil while the VIN is NULL, and a **VIN-source** pill.
- **Planning ack** "Customer dealer" free-text → a structured **dealer dropdown** (`is_dealer`
  customers); the picked dealer lands on the chassis at ack.
- **Admin → Customers** (new): searchable 2160-list + customer detail + **Contacts** panel CRUD
  (add / inline-edit / set-primary / soft-delete) + an `is_dealer` toggle.
- Migration **0022** (cross-schema): `customers.is_dealer`; `customer_contacts` (+ partial-unique +
  2147-row backfill); `chassis_records.dealer_id` (cross-schema FK, SET NULL) + `vin_source`.
  Round-trips clean; zero net-new autogenerate drift.
- **25 dealers** seeded (`is_dealer`); `dealer_seed_decisions.csv` committed.
- 3 new per-role journeys green (dealer capture, customer contacts, VIN late-entry); backend tests
  for contacts CRUD + the VIN NULL-guard.
- **Parallel hotfix PR #28** (prejob calc.status sync) merged separately — see footnote 10.
- v4.31–v4.34 + v4.33.1 surfaces untouched; `/calculator` byte-identical.
