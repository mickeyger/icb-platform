# v4.25 screenshots — rules-table engine foundation

Captured via `frontend/scripts/capture-v425.mjs` (Playwright headless against the unified
FastAPI app on :8000, autologin = admin, migration 0009 applied + 9 rules / 6 lookups seeded).

- **admin-bom-rules.png** — the read-only Admin › BOM Rules inspector: the 9 Freezer × Vacuum
  panel rules (formula expressions + priorities) + the 6 `spec_to_sap_code` lookups. The
  admin-gated "Rules" nav entry is visible (autologin user is admin).
- **admin-bom-rules-fullpage.png** — full page incl. the price-overrides table (empty — live
  SAP/OITM pricing in effect).
