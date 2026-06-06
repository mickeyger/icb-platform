# v4.26 screenshots — DDM resolution + admin CRUD

Captured via `frontend/scripts/capture-v426.mjs` (Playwright headless, :8000, autologin=admin,
migrations 0010 + spec_options/rules/lookups seeded). One per admin sub-screen + the create modal.

- **admin-spec-options.png** — the DDM dropdown catalogue (115 options). Note `body_type='*'`
  (field-scoped/body-agnostic), `SAP code = —` (NULL — combination-bound, ADR 0014), and
  `Explosive (NOT AVAILABLE)` seeded inactive.
- **admin-rules.png** — the 9 Freezer × Vacuum rules with formula text (editable).
- **admin-lookups.png** — the 6 `spec_to_sap_code` lookups (the combination → SAP-code map).
- **admin-price-overrides.png** — price overrides (empty by default; live OITM pricing otherwise).
- **admin-rules-create-modal.png** — the create form with the live formula-validate control.

All four screens are admin-gated (`AppData.isAdmin`); the "Admin" nav entry only shows for admins.
