# ADR 0022 — Pre-Job Card polish + the multi-mounting fridge deferral (v4.33.1)

- Status: Accepted
- Date: 2026-06-14
- Work Order: v4.33.1 — Pre-Job Card Polish Bucket (bundles v4.33-deferred items + Michael's
  demo-walkthrough UX catches)
- Note: a brief polish-bucket ADR (§0.12). The v4.34.1 dealer-DDM work will fold its own section in
  here when it ships.

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
