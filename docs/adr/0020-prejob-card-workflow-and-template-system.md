# ADR 0020 — The Pre-Job Card workflow, template system, and the v4.33 pattern ledger

- **Status:** Accepted
- **Date:** 2026-06-12
- **Work order:** v4.33 (Phase 3 §4.7 — Pre-Job Card Modal + Template Migration + 3-Role Sign-off + Email)

## Context

v4.33 is the first concrete step toward replacing SAP B1's quote/job-card function (Nadie's
timeline: MES live ~Dec 2026, parallel run Jan–Apr 2027, SAP cut-off ~Apr–May 2027). It ships
the Pre-Job Card workflow: Nadie's 22-template Word library becomes a database-backed,
admin-reviewed template system; the mock send-dialog becomes a preview-and-edit modal; an
internal 3-role sign-off chain replaces the legacy 2-role job-level columns; and a
transitional mailto+PDF email path stands in until SMTP (v4.36+). v4.36's Job Card generation
(the actual SAP-replacement endpoint) builds directly on these decisions.

## Decisions

### 1. JSONB sections — one shape for eight product classes (§0.5)

`sections = [{name, items: [{text, note?, sub_items?[], sap_item_code?}]}]`. Section names and
counts vary by product class (truck bodies: GRP + SUB FRAME + FINISHING; complete trailers:
STEEL SECTION; body-only retrofits: CHASSIS MODIFICATIONS) — the array shape absorbs all of
them, so ONE editor, ONE modal, ONE PDF renderer serve every class. `note` carries clarifying
lines ("Rear will be solid panel"); `sub_items` carries structured packs (the Explosive
HazChem equipment list); `sap_item_code` is the §0.10 capability stub — the field shape ships
in v4.33, the OITM lookup mechanism is v4.33.1, gated on SAP MS SQL access (#178). The shape
is validated by ONE set of pydantic schemas (`schemas/prejob.py`) used by the admin editor,
the modal, and the importer's consumers — malformed sections 422 identically everywhere.

### 2. The 3-role workflow — and the §0.21 supersede of the legacy signoff machine

Internal Sales (sales role) **creates**; Sales Rep (sales role, distinguished by workflow
position) + Planner (planner role; admin backs up per Q4 — production deliberately excluded)
**check-sign**; both sign-offs auto-flip `pre_job_confirmed`. `prejob_cards` is the source of
truth. The legacy `production_jobs` pre-job machine is driven through its STATUS columns only
(`pre_job_sent_at`, `pre_job_confirmed_at`, status) so Planning's ack gate keeps working —
the legacy job-level SIGNOFF columns are **never written** by the new flow (planner ≠
production; mirroring would fabricate an attestation that never happened). Legacy rows
in-flight at ship complete on the old path; new cards never touch it. Two negative-grant
tests pin this honesty permanently.

**Audit honesty rules ("record the truth, not the symmetry"):** the ACTUAL signer overwrites
the assigned one (Burt signing as planner backup shows Burt + his attestation, not Simeon);
a reject resets BOTH sign-offs (the re-submitted card is re-checked by both roles, not just
the rejector) and prefixes the captured reason with who rejected.

**The UI supersede (the user-facing half — completed pre-merge after a click-test catch):**
§0.21 said "the old PreJobSignoffModal becomes unreachable for new cards," but that was only
the server-side column discipline. The legacy sign-off SURFACES still rendered for new cards —
a duplicate, permanently un-tickable checkbox widget on the Costings detail page, a stale
"awaiting both" bottleneck dot on the dashboard, and empty "Sales/Production sign-off: —"
lines on the Planning ack panel — all reading the columns the new flow never writes. The fix
is one bulk read: `GET /api/prejob-cards/summaries` returns each calculation's card state,
merged onto every costing as `prejob_card`; the detail panel, the dashboard dot, and the
Planning provenance all gate on that ONE field. New-flow cards drive a new status panel (status
pill + Sales Rep / Planner rows from the card); legacy rows with no card keep the old widget.
One card → one sign-off surface, everywhere.

### 3. Workflow constraints — one card per costing (service-level, deliberate)

The costing reference is canonical (§0.7 — no Pre-Job Card numbering), and creation 409s if
ANY card exists for the calculation. This is a **service-level rule, not a DB UNIQUE** —
chosen deliberately: the rejected-card path returns the SAME card to draft (history intact:
reject_reason, attestation resets), and a "fresh start" is the draft's **template switch**,
which re-seeds sections from the newly chosen template. There is intentionally NO card-delete
endpoint in v4.33. If real usage demands supersede-with-history (multiple card generations
per costing), that becomes a v4.33.1 conversation — the schema's `version` column and the
service-level (not schema-level) constraint keep that door open without a migration.

### 4. Review-and-normalize template migration (§0.15)

The 22 Word templates imported as `is_active=False` drafts; BA/Nadie approve each in the
admin editor. The gate is STRUCTURAL: the modal's selector lists active templates only — a
half-reviewed template cannot be sent against, by construction. Content fixes are
**content-keyed, never positional** (the Icecream Mid/Big doorframe drop matches the
`DRD…3Cr12` text — a future template isn't at risk just because something sits at index 2).
Protection is two-sided: the admin API 409s deletes of active templates, and the importer's
`--update` refuses to overwrite them. The importer parses the documents' ACTUAL structure —
the Explosive template lays its sections out as a 2-column Word TABLE invisible to
`doc.paragraphs`; the parser walks both layouts (the dry-run pattern surfaced it: 21/22
parsed, one anomaly, structural cause found, fixed at the parser level).

### 5. Template-variable substitution — parity-by-construction for templated text

ONE engine (`services/template_variables.py`): `{{token}}` placeholders resolve from a
context dict with locked semantics — key ABSENT → token stays VISIBLE (a missing binding is
spottable, never silently blanked); present-but-empty → "Pending" for `{{vin}}`, blank
otherwise; lengths format `5 400`. Core tokens BAKE at card creation ("substitutions become
invisible at modal-open"); fridge tokens stay visible until the dropdown selects a unit (the
modal mirrors the engine's exact semantics for the live replace; a SWITCH rewrites the
previous display name); the PDF renderer does a defensive final sweep so a token with a known
value can never ship. The admin editor shows raw tokens (the structural-gate shape: drafts
visible, consumers resolved). Verification note: the spec sketch named
`calculations.length_mm` columns — the REAL source is `dimensions_json {length,width,height}`
in METRES; the context builder converts, and a test asserts against live rows.

### 6. Fridge DDM (`fridge_units`, migration 0018)

30 rows / 8 manufacturers transcribed from Standard Drawing FRIDGE MOUNTING A (Front Mount),
data oddities kept verbatim (Thermoking V300 905×50; Corunclima width-only). `display_name`
fills `{{fridge_make}}`; mounting drawing + cutout dims fill the bonus tokens. Drawings
B/D/F/G/H (other mounting styles, per-style cutouts) are the v4.33.1 enhancement — extra rows
or a `mounting_styles` JSONB, decided then. Flat shape → the generic v4.26 AdminCrudTable
serves the admin screen with config only.

### 7. Email via mailto — the transitional pattern (§0.11, corrected)

No SMTP in v4.33. The honest mechanics: **mailto cannot carry attachments** (Outlook/Gmail
ignore every attach param) — so the email endpoint builds subject + body with BOTH
click-to-signoff deep links, the mail draft opens with **To: blank** (users carry no email
column until v4.34's notification config) and **CC pre-filled** from the card's
`cc_recipients`; the PDF attaches manually via the Download button. ONE renderer
(`GET /{id}/pdf`) feeds the Preview button, the Download buttons, and the submit-time records
snapshot (`pdf_file_id`, best-effort — a render failure never blocks a submit). v4.36+
replaces the delivery mechanism; everything else (links, PDF, CC) carries over.

### 8. `sales_rep_user_id` quote-time capture (§0.13)

Nullable FK on `icb_costings.calculations` (the only icb_costings DDL in the WO) — captured
at quote time when Nadie knows the rep; defaults the modal's Sales Rep dropdown; the calc's
`user_id` (creator) is the soft fallback. Empty allowed — the dropdown opens unselected.

### 9. CC recipients — store raw, filter at consumer

`prejob_cards.cc_recipients` (migration 0019) stores exactly what Nadie typed
(comma-separated free text); only email-shaped entries feed the mailto `&cc=`. Her typo stays
visible in the field for her to fix; the mail client never receives garbage; no upfront
validation friction. **The reusable rule for free-text fields where strict validation would
frustrate but consumer pollution would corrupt: store raw, filter at the consumer.**

## Test-strategy ledger (the v4.33 accumulation)

Patterns that each bit once and are now pattern-fixed:

1. **Negative-grant tests** — seed the permission AND assert the deliberate absence
   (production has no prejob grant; the legacy signoff columns stay NULL — twice).
2. **Derive preconditions, don't assume them** — tests select FREE bays/rows from current
   state; positional assumptions break on interactive-dev leftovers.
3. **Spec-vs-tree verification before building** — twice load-bearing in this WO
   (`length_mm` columns that don't exist; "23 templates" that were 22).
4. **Parse the document's actual structure, not its assumed one** — the table-layout
   template; surfaced by the dry-run-first discipline.
5. **Structural gates over procedural gates** — active-only selectors, draft-only deletes;
   the code enforces the review rule, humans don't remember it.
6. **Shared validation schemas over duplicated checks** — one pydantic shape, identical 422s
   in every writer.
7. **Two-sided safety rails** — UI 409 + importer refusal protect the same asset from both
   code paths.
8. **Gates with explicit waivers** — §0.8 blocks by default; the exception is a visible,
   deliberate checkbox, not a hidden bypass.
9. **Safety-rail escape hatches leave audit trails** — `--include-active` exists for the
   foreseeable case (Michael had already approved all 22), and every row it touches gets a
   version bump + `token-normalizer` stamp for re-review.
10. **Record the truth, not the symmetry** — actual signer captured; rejects reset both
    checks; reasons carry who rejected.
11. **Store raw, filter at consumer** (CC — decision 9).
12. **Journey infra: no mid-modal full-page screenshots** — they scroll the page under
    fixed-position modals and destabilise clicks ("element is not stable/detached").
13. **Journey infra: mid-test actor switching needs `clear_cookies()`** — the SPA autologin
    reuses an existing session (v4.29 note), and the autologin POST 403s through the CSRF
    middleware when a session cookie is already present.
14. **Journey infra: role-filtered dropdowns need the `role_users` fixture** — an empty
    select dead-ends `select_option` with no useful error.
15. **Journey infra: mailto auto-fire is headless-safe** — chromium drops the unhandled
    protocol and stays on-page; assert on surviving banners/toasts.
16. **Direct observation over retry loops** (the meta-discipline) — every §3.7 failure was
    root-caused by staging the page and looking (probe scripts, response listeners), not by
    re-running until green; the page was provably correct throughout — all four bugs were in
    test mechanics or test data.
17. **Supersede the SURFACES, not just the columns** — §0.21's "never write the legacy
    columns" rule is only half a supersede; every UI that READS those columns must gate on
    "does a new card exist?" too. A pre-merge click-test caught three that didn't (the detail
    widget, the dashboard dot, the Planning ack lines). One bulk summary field (`/summaries` →
    `prejob_card` on every costing) feeding all three beats per-row fetches and stops the
    surfaces drifting apart.
18. **Journey infra: an external `:8001` server must mirror the harness's env** — running the
    suite against a hand-started server (`MES_BASE` set) requires `MES_DEMO_AUTOLOGIN_USER=admin`
    AND the server's own origin in `ALLOWED_ORIGINS` (e.g. `http://127.0.0.1:8001`, which is not
    a default). Miss the origin and autologin 403s → every API 401s → the SPA renders a
    misleading "costing not found" page that reads as a frontend bug. Diagnosed by capturing the
    SPA's OWN network status codes (all 401, incl. `/api/session`), not by trusting the rendered
    symptom — the direct application of ledger item 16.
19. **Symptom-key your recipes** — a fix filed under what it IS ("local journey-verify recipe")
    won't surface when you're scanning by what you SEE ("all-401 / costing not found"). Item 18
    was *already* in memory and still cost ~20 minutes, because debugging searches symptoms, not
    solution-names — and the verify-by-name entry didn't match the failure signature in the
    moment. Index durable fixes by their symptom, and actually search memory when stuck. The
    recall path is the part of the loop most engineers never debug in themselves; it's as much a
    correctness surface as the code.

## Consequences

- v4.36's Job Card generation reuses: the sections JSONB + renderer (same document, workshop
  audience + SAP customer-block), the PDF infrastructure, the substitution engine, and the
  status machine's `pre_job_confirmed` trigger point.
- v4.34's notification system replaces the mailto delivery and adds user email addresses;
  the email-content builder (links, subject, CC) carries over unchanged.
- v4.33.1 queue: SAP item-code lookup (#178), fridge drawings B/D/F/G/H, Medical Waste
  template (from the Explosive base if Nadie doesn't supply one), card supersede-with-history
  if usage demands it.
- Deferred forever: any customer-facing Pre-Job surface (§0.2 — internal only, Nadie Q3).
