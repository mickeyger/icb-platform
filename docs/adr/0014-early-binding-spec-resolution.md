# ADR 0014 — Early-binding via combination resolution (DDM spec → SAP code)

- **Status:** Accepted
- **Date:** 2026-06-06
- **Work order:** v4.26 (Phase 3 §4.1 — DDM dropdown→spec resolution + admin CRUD)

## Context

Nadie's costing workflow is "I see dropdowns; the system sees SAP codes from the start"
(the **early-binding** principle). v4.26 implements the dropdown→spec resolution layer
(`icb_mes.bom_spec_options` + the `DDMResolver`) feeding the v4.25 rules engine. The design
question: **where, exactly, does a selection acquire its SAP code?**

The naïve reading of "each dropdown selection carries a SAP code" doesn't hold against the
Costing Module's reality (surfaced in the v4.26 pre-flight of the `DDM's & Functions` sheet):

- The UI has **separate per-attribute dropdowns** — `roof_material` ("EPS 24DV") and
  `roof_material_thickness` ("76") are independent fields.
- A SAP code is a property of the **combination**, not either field alone: a *76 mm EPS 24DV*
  panel (`GRP-MPS-A-0077`) is a different SKU from a *56 mm PU 32DV* panel (`GRP-POL-A-0158`).
  The string "76" or "EPS 24DV" on its own maps to no SKU.
- The DDM options are **field-scoped and largely body-type-agnostic** (`roof_material` has the
  same 5 options across all body types), so they seed as `body_type = '*'`.

## Decision

**The SAP code binds at the (material × thickness) COMBINATION, at resolution time — not on every
individual dropdown option.**

- `bom_spec_options.sap_code` is **nullable and usually NULL.** Per-option codes are populated only
  for genuinely 1:1-coded options (e.g. a fridge-unit dropdown where one option *is* one SKU).
- The panel's SAP code is resolved by the **combination lookup** the v4.25 engine already owns:
  `icb_mes.bom_rule_lookups (lookup_type='spec_to_sap_code', key='<material>|<thickness>') → ItemCode`.
- The flow: `DDMResolver.resolve_jobspec_raw` turns dropdown labels into a resolved `JobSpec`
  (each panel's material + thickness), and the engine binds the code from the combination during
  generation. So the **resolved spec carries its SAP code before the geometry runs** — the
  early-binding promise is *kept*, just delivered at the combination level.
- `resolve_spec` tries the exact `body_type`, then falls back to `'*'` (matching the body-agnostic
  option catalogue).

So: **"early-binding" = the resolved job spec knows its SAP codes before BOM generation, via
material×thickness combinations — NOT "every dropdown option stores a code."**

## Consequences

- **Admin UX (the NULL-sap_code question):** in the spec-options admin screen, `sap_code` is blank
  for most rows — that is correct, not missing data. The SAP code lives on the **lookups** table
  (the combination map), which is its own admin screen. Future admins edit the combination→code
  mapping there; they don't (and shouldn't) put a code on every thickness/material option.
- **Scaling (cf. the v4.24 spike report):** each section/material-family needs its description/
  combination→code map (a known data-entry cost), but the per-field option catalogue stays small and
  body-agnostic. This is the data-driven shape the v4.24 spike recommended.
- **Validation:** when an admin *does* set a per-option `sap_code`, it is validated against
  `icb_sap.OITM` (read-only, ADR 0013) — an FK-shaped app-layer check, not a DB FK (the v4.23
  deferred-FK lesson: a hard cross-schema FK breaks the independent ETL reload cycles).
- **Body types:** v4.26 proves resolution scales to all 8 body types; per-body-type *geometry rules*
  (and thus full non-Freezer BOMs) arrive in v4.27 — until then, non-Freezer specs resolve correctly
  but generate an empty BOM (no rules), which is the documented v4.26 boundary.

## Alternatives rejected

- **A `sap_code` on every dropdown option.** Wrong granularity — "76" / "EPS 24DV" alone aren't
  SKUs; it would force fabricating codes or leaving most blank-but-required, and duplicate the
  combination logic.
- **Collapsing material + thickness into one "panel material" dropdown** (e.g. "76mm EPS 24DV" → one
  code). Cleaner for binding but it doesn't match the real two-dropdown UI Nadie uses, and explodes
  the option list (material × thickness combinatorially) instead of keeping two small field lists.
- **A hard cross-schema FK** `bom_spec_options.sap_code → icb_sap.OITM` — rejected per ADR 0013
  (breaks independent ETL reloads); validated at the app layer instead.
