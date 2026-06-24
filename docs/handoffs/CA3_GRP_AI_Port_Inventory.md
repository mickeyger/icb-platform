<!--
  PROVENANCE: This is a COPY for MES-side accessibility. Canonical home is the
  GRP-Costing-System repo  ->  docs/CA3_GRP_AI_Port_Inventory.md (commit d0e4750, branch main).
  Filed into icb-platform as the v4.38 section-3.0 discovery output. CA4: commit this into the
  v4.38 branch as your discovery artifact. If the GRP canonical changes, the BA re-syncs this
  copy. Dropped locally 2026-06-23 (remote push intentionally not performed).
-->

# CA3 — GRP → MES AI Port Inventory

**Prepared by:** GRP-Costing-System CA (post-v4.37 stand-down)
**Date:** 2026-06-23
**Source repo:** [GRP-Costing-System](https://github.com/mickeyger/GRP-Costing-System) `main` @ `a077987`
**Stack (source):** FastAPI + Jinja2 + vanilla JS, SQLAlchemy on **MySQL** (prod) / SQLite (dev)
**Target (MES):** `icb-platform` — FastAPI + React/TypeScript, SQLAlchemy on **PostgreSQL**

---

## 0. Who consumes this & how

| Consumer | Scope | Read |
|---|---|---|
| **CA4 → v4.38** | Port the **GRP AI** (Help assistant + Auto-Update/Excel-Audit/Reconcile) into the MES | **Parts A, B, D, E** |
| **v4.37 CA** | Port the **Cost Calculator** surface | **Parts C, D, E** |

**Companion doc (already written):** [`docs/BA_RELEASE_BRIEFING_2026-06-19.md`](BA_RELEASE_BRIEFING_2026-06-19.md) — contains the **ready-to-run Code-Agent prompt** and the **PostgreSQL** versions of the migration SQL. This inventory is the *source map*; the BA briefing is the *execution prompt*. Use both together.

> ⚠️ **Two parallel systems, do not cross-contaminate.** The live GRP app (`/calculator`, `/`) must stay bit-for-bit pristine (memory: `reference_doc_maintenance_protocol`). The MES has its **own copy** of the calculator backend (`backend/app/routers/calculator.py`) and a React frontend — code is **not** cherry-pickable; it must be re-implemented per the caveats below.

---

## Table of contents
- **Part A** — AI Help Assistant (chat, tools, prompts, logging)
- **Part B** — Auto-Update / Excel-Audit / Reconcile (deterministic, no LLM)
- **Part C** — Cost Calculator (for v4.37 CA)
- **Part D** — Cross-cutting dependencies, environment & the WeasyPrint/Pango landmine
- **Part E** — Prompts debugged (consolidated)
- **Part F** — Port verification checklist & open items

---

# Part A — AI Help Assistant  *(CA4 / v4.38)*

A self-contained, permission-gated conversational assistant powered by Claude. Streams replies as SSE, calls **read-only** tools that respect per-user permissions, and can *offer* (never silently run) an Auto-Update costing run.

## A.1 Files

| Path | Purpose |
|---|---|
| `app/routers/help.py` | All `/api/help/*` routes: SSE chat, attachment lifecycle, audit, auto-fix orchestration, rate-limit, request logging |
| `app/help/__init__.py` | Loads `app_guide.md` (mtime-cached); `get_app_guide()`, `get_model()`, `is_configured()` |
| `app/help/prompts.py` | System-prompt assembly (cache-control blocks) + per-turn user-message builder (page context + reconciliation injection) + history truncation |
| `app/help/tools.py` | 8 read-only tools + `propose_actions` validator; permission-gated dispatcher (allowlist) |
| `app/help/redact.py` | Post-filter that blanks price/cost/total fields when user lacks `bom.view_prices` / `bom.view_full_cost` |
| `app/help/app_guide.md` | **Curated knowledge base** (System-Block-2). Hot-reloaded on file change; ~250 lines of menu structure + Q&A. **This is the file you edit to teach the assistant a new flow — not a DB row.** |
| `app/static/js/help_chat.js` | Floating launcher + right-edge chat panel; SSE parsing; history+attachment in `localStorage` |
| `app/static/js/help_audit.js` | Left/right "Excel Audit" panel; calls `/api/help/audit`; right-click "Investigate section" |
| `app/static/js/help_autofix.js` | Client orchestrator for Auto-Update loop (state machine; **no LLM**) |
| `app/static/css/help_chat.css` | Launcher (z-9000) + chat panel (right, 420px, z-9100) |
| `app/static/css/help_audit.css` | Audit panel (left/right, 460px, z-1100) |

## A.2 Anthropic integration

| What | Value | Source |
|---|---|---|
| SDK | `anthropic>=0.40` | `requirements.txt:27`, `app/requirements.txt:24` |
| Streaming dep | `sse-starlette>=1.6,<2.0` (pinned `<2.0` — newer needs starlette ≥0.49, conflicts with fastapi 0.115) | both requirements files |
| **Model (default)** | **`claude-haiku-4-5-20251001`** | `app/help/__init__.py:41` |
| Model override | env `ANTHROPIC_HELP_MODEL` | `app/help/__init__.py:45` |
| Client | `AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY",""))`, constructed **inside** the stream generator so a missing key never crashes startup | `app/routers/help.py:164-176` |
| Key | env `ANTHROPIC_API_KEY`; if absent → `/health` returns `configured:false` and the floating button is hidden; `/chat` returns **HTTP 503** | `app/routers/help.py:458-459` |
| Loop | `client.messages.stream()`, `max_tokens=1024`, **max 6 tool-use iterations** | `app/routers/help.py:204-276` |
| Caching | System blocks 1+2 (persona + app_guide) tagged `cache_control:{type:"ephemeral"}` | `app/help/prompts.py:116-127` |
| ⚠️ "Streaming" caveat | Response is **buffered in memory** then returned as one `text/event-stream` `Response` — the middleware stack broke true SSE. Port can keep this shape or do real SSE if the MES middleware allows. | `app/routers/help.py:520-540` |

## A.3 Endpoints (`/api/help/*`, all require an authenticated user)

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET | `/health` | user | `{configured, model, rate_limit_per_hour}` — frontend gates the button on this |
| POST | `/chat` | user | SSE stream; body `{message, history, page_context?, attachment?, reconciliation?}`; events `token`/`tool`/`actions`/`done`/`error`; **30 req/hr/user** |
| POST | `/attachment` | `bom.view_prices` | Upload `.xlsx`/`.xls` (≤5 MB, 2-hr TTL) → `{upload_id, sheets, picked_sheet}` |
| DELETE | `/attachment/{upload_id}` | user | Detach (best-effort 200) |
| POST | `/audit` | `bom.view_prices` | Direct reconciliation JSON (uncapped) |
| POST | `/auto-fix/plan` | `bom.auto_update` | Build the next fix-step (see Part B) |
| POST | `/auto-fix/apply-prices` | `bom.auto_update` | Persist unit-price overrides as one undoable batch |
| POST | `/auto-fix/apply-formulas` | `bom.auto_update` | Persist validated formula updates |
| GET | `/server-workbooks` | `bom.view_prices` | List Excel files in the configured costing folder |
| POST | `/attachment/server` | `bom.view_prices` | Attach a workbook from that folder without uploading |

## A.4 `help_request_log` table

Model `HelpRequestLog` (`app/database.py:875-894`). One row per request, written from a **separate `SessionLocal()`** in `_persist_log()` (`app/routers/help.py:117-141`) so it never pollutes the request session.

Columns: `id, user_id(FK,nullable), created_at(idx), model, input_tokens, output_tokens, cached_tokens, cache_write_tokens, ms_elapsed, page, tool_calls, tool_names, finish_reason, error`.

> ⚠️ **New-table-on-prod caveat** (memory: `feedback_prod_new_tables_manual`): `Base.metadata.create_all` does **not** reliably create a brand-new table on a Passenger restart. On GRP prod it had to be created manually via cPanel Terminal. **For the MES Postgres, create this table explicitly during the v4.38 migration** — don't assume `create_all` does it.

## A.5 Guardrails (these ARE the product — port them faithfully)

1. **No code/implementation disclosure** (`prompts.py:29-36`): no file names, functions, table/column names, routes/URLs, framework/library names, or code snippets. May explain *business* data-flow only. (Memory: `feedback_help_no_code_disclosure`.)
2. **User/auth data is off-limits to everyone, incl. admins** (`prompts.py:51`) — no users/passwords/sessions/permissions lookups. Enforced *structurally*: the 8 tools (`tools.py:485-494`) cannot touch auth tables.
3. **Read-only** (`prompts.py:53`) — the assistant never writes; it explains steps.
4. **Permission-respecting tools**: each tool checks `user_can()` first and pipes results through `redact()`.
5. **Action allowlist** (`tools.py:410-480`): only types `highlight_bom_lines|highlight_element|scroll_to|navigate|auto_update_costing`, a fixed target list, and a fixed nav-path list. Anything else is rejected.
6. **Rate limit** 30/hr/user; **attachment** ≤5 MB, `.xlsx/.xls` only, 2-hr TTL.

## A.6 Port caveats (A → React/Postgres)

- The **system prompt is UI-coupled**: action types, targets and nav paths in the prompt must match the MES React routes/components, or the buttons will 404. Re-map `navigate` paths (`/admin/materials`, `/calculator`, …) to MES routes **and** update the prompt's allowlist in lockstep.
- `page_context` is whatever the frontend posts (≤8000 chars) and `reconciliation` (≤60000 chars) — the React app must assemble the same shapes.
- Keep **Haiku** (`claude-haiku-4-5-20251001`) for cost unless the MES wants richer answers; just set `ANTHROPIC_HELP_MODEL`.
- The knowledge base (`app_guide.md`) is **GRP-specific**; the MES needs its own guide describing MES screens, or the assistant will cite menus that don't exist.

### A.6.1 Current MES route surface (for the `navigate` allowlist)

- **v4.38 (Feedback Portal)** classifies issues; it does **not** navigate users — so the `navigate` allowlist barely matters for CA4, which need not finalize it.
- **v4.37 (Cost Calculator AI port)** is where the allowlist is critical; the **v4.37 CA finalizes** it against the then-current MES routes. Starting list (grows as v4.36b/c/.5/.37/.38 ship):

```
/mes-app/                     — React MES home (currently 307 → /login)
/mes-app/planning             — Planning Board
/mes-app/chassis              — Chassis List + Detail
/mes-app/costings             — Costings Dashboard
/mes-app/costings/new         — New costing entry point (was iframe to GRP; now native — see Part C)
/mes-app/prejob               — Pre-Job Card flow
/mes-app/admin/               — Admin landing
/mes-app/admin/outstanding    — Outstanding Sign-offs (v4.33.1)
/mes-app/admin/merge-chassis  — Merge Chassis (v4.36a §3.6)
/mes-app/admin/find-orphan    — Find Orphan Chassis (v4.36a §3.6)
/mes-app/admin/restore        — Restore deleted chassis (v4.36a §3.6 STEP 7)
/mes-app/admin/health-check   — Health Check (v4.36b — lands week of 30 Jun)
/mes-app/admin/feedback       — Feedback Inbox (v4.38 — lands week of 30 Jun)
/calculator                   — Jinja Cost Calculator (legacy GRP — byte-identical, see §D)
/login, /logout, /admin       — Jinja auth + admin
```

---

# Part B — Auto-Update / Excel-Audit / Reconcile  *(CA4 / v4.38)*

**100% deterministic — no LLM anywhere in this path.** The assistant only *offers the button* and *narrates the final report*. Reconciliation compares an uploaded Excel workbook against the live on-screen costing; Auto-Update aligns insulation + unit prices (formulas are proposed, never auto-applied).

## B.1 Files

| Path | Purpose |
|---|---|
| `app/help/reconcile.py` | Reconciliation engine: parse Excel → flatten to sections/items → diff vs live result → classify each delta `price\|formula\|rounding\|unexplained\|match`; extract insulation control-block (6 locations × EPS/PU + Y/N flags); fuzzy sheet-name picker |
| `app/help/autofix.py` | **Fix-plan builder (pure logic).** One prioritized step per call: (1) insulation EPS/PU + thickness, (2) unit-price overrides, (3) formula **proposals**. Validates candidate formulas through the app's own engine before proposing |
| `app/excel_importer.py` | `_detect_sheet_totals_column()` (dynamic totals column) + per-section multiplier extraction |
| `app/excel_cell_resolver.py` | Cell-chain resolver; external-ref regex; `urllib.parse.unquote()` |
| `app/excel_formula_scanner.py` | Finds rows linked to `FORMULAS 2018.xls` via the xlsx ZIP's externalLink rels |
| `app/static/js/help_autofix.js` | Client loop: POST `/plan` → preview → apply (client lever for insulation/options, server API for prices) → recalc → re-plan, until balanced/capped; renders report + Undo |
| `window.calcAutoFix` in `app/static/js/calculator.js:6065-6248` (support `434-510`) | Adapter the loop drives: read/apply insulation & body-option state, session/permanent overrides, reload BOM, recalc, return slim live result |

## B.2 Fix-plan builder — `build_fix_plan()` (`app/help/autofix.py:69`)

```python
def build_fix_plan(report, excel_insulation, live_insulation_state,
                   eval_ctx=None, pass_no=1, db_ctx=None,
                   live_option_state=None) -> dict:
```

- **In:** uncapped reconciliation (`include_ids=True, caps=False` — carries `live_bom_id`, `waste_pct`, `section_multiplier`); Excel insulation state; live insulation state; `eval_ctx` (geometry+variables+formula library); `db_ctx` (override protection); live body-option state.
- **Out:** `{pass, step:"insulation"|"prices"|"none", balanced, summary, actions[], proposals[], ignored[], warnings[]}`.
- **Step order & helpers:** insulation `_diff_insulation()` + `_diff_option_flags()` (`221-399`) → prices `_price_action()` (`412-432`) → formulas `_formula_action()` (`438-498`, **propose-only**, validated via `evaluate_formula()`).
- **Tunable constants:** `AUTOFIX_FORMULA_MIN_DELTA=1.00 R`, `AUTOFIX_BALANCED_EPSILON=0.05 R`, `THICKNESS_EPSILON=0.0005 m`, `QTY_EPSILON=0.011`.

## B.3 Permission `bom.auto_update`

- **Defined:** `app/database.py:1715` — granted to roles `{admin, full, user}` by default.
- **Enforced:** `_require_auto_update()` (`app/routers/help.py:614-619`), checked **first** on all three write endpoints (`/plan` 646, `/apply-prices` 729, `/apply-formulas` 818).

## B.4 Excel-handling landmines (these cost real debugging time — keep them)

1. **External-link Targets are URL-encoded** (`excel_formula_scanner.py:66-84`): decode with `urllib.parse.unquote()` before substring-matching `"FORMULAS 2018"`. (Memory: `feedback_openpyxl_external_links`.)
2. **Totals column is dynamic** (`excel_importer.py:455-494`): standard sheets use col **J**; wide sheets (SRD/DRD, "4.9 & UP CHILLER") use up to col **U**. Detect by scanning the GRAND-TOTAL row for the rightmost `=SUM(...)`. (Memory: `feedback_excel_audit_totals_column`.)
3. **Inactive sections/rows filtered** (`reconcile.py:29-34, 349-390`): Excel col-J total ≤ 0.01 R ⇒ section dropped (option not picked). A missing section is **correct**, not an error — the prompt is explicitly told not to flag it.
4. **Per-section multipliers already applied** (e.g. SIDES ×2) in both Excel col J and live result — never divide/double report numbers.
5. **Rounding noise is not a cost diff**: Excel ROUND() is half-up; app uses banker's rounding. Drift ≤0.05 R is classified `rounding` and excluded from auto-fix.
6. **Dimension mismatch suppresses formulas**: if Excel vs live geometry differ >0.01 m, formulas aren't auto-fixed (Excel qty formula is only valid for Excel's dims).

## B.5 Port caveats (B → React/Postgres)

- **No hard-coded category/location names** (memory: `feedback_no_hardcoded_category_names`). Insulation pairs are found by `is_body_option=True` + matching `group+subgroup` + names containing "EPS"/"PU". Body-option radio sets = ≥2 members in the same group+subgroup. Preserve this — don't match literal strings.
- **Price overrides** live in `BillOfMaterial.unit_price_override` (nullable). Session overrides (`localStorage bom_price_overrides`) must be cleared before recalc. Undo restores the *prior* override (or `None`).
- **Undo batches** are keyed by a shared `batch_at` timestamp in `BomOverrideHistory`.
- **Formulas are never auto-applied** by design (sheets cache stale values; only human review catches it). Keep proposal-only.
- The whole loop is a **pure state machine** — re-implementable in React without any AI dependency.

---

# Part C — Cost Calculator  *(v4.37 CA)*

> ✅ **DECISION (22 Jun PM — v4.37 outline Q1 = Option A): native React calculator.** v4.37 retires the GRP iframe entirely; the MES owns a **fully native React Cost Calculator**. The AI-features port is now in **v4.37 core scope** (per the 22 Jun PM v0.2 outline revision), not deferred. **Iframe path closed** — every Part C feature, including C.4 (Configuration Summary modal + contextual edit-save labels), must be **re-implemented in React**; nothing comes "free" from an embedded GRP page.

## C.1 Files

| Path | Purpose |
|---|---|
| `app/static/js/calculator.js` (~6357 ln) | Primary calculator UI: dimensions, body options, overrides, margin/discount, approve/edit, version tracking |
| `app/static/js/calculator2.js` (~5541 ln) | "Costings 2" variant — includes all items, no body-option gating; mirrors most logic |
| `app/templates/calculator.html` / `calculator2.html` | Page templates (extend `base.html`) |
| `app/routers/calculator.py` (~1192 ln) | `/api/calculate`, `/api/approve`, `/api/check-duplicate`, `/api/calculations` list/detail |
| `app/routers/trailers.py:274-334` | `PUT /api/bom/{bom_id}` dual-mode |
| `app/routers/exports.py:434-513` | `GET /results/{id}/export/pdf` (WeasyPrint + Jinja) |
| `app/templates/reports/cost_breakdown.html` | PDF template |
| `app/database.py:366-431` | `CalculationRecord` model (`result_json`, `dimensions_json` are `_BigJson` = LONGTEXT on MySQL) |

## C.2 Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/calculator`, `/calculator2` | user | Render pages |
| POST | `/api/calculate` | user | Core calc: formula engine → cost breakdown |
| GET | `/api/check-duplicate` | user | `{has_duplicate, count, max_version, next_version, records[], parent_quote_number}` |
| POST | `/api/approve` | user | Save: create/edit `CalculationRecord`, `assign_quote_number`; `version_action ∈ {replace,new_version,overwrite}`, `edit_record_id`, `is_repair` |
| GET | `/api/calculations` | user | List saved (filters; default limit 20) |
| GET | `/api/calculations/{id}` | user | Fetch for edit |
| POST | `/api/calculations/{id}/accept` (legacy `/approve`) | user | Mark accepted |
| POST | `/api/calculations/{id}/decline` | user | Mark declined + reason |
| DELETE | `/api/calculations/{id}` | **admin** | Delete |
| PUT | `/api/bom/{bom_id}` | **dual-mode** | `variable_value` and/or `unit_price_override` only → `require_user`; any other field → `require_admin` |
| GET | `/results/{id}` | user | Result page |
| GET | `/results/{id}/export/pdf` | `export.pdf` | WeasyPrint PDF |
| GET | `/results/{id}/export/excel` | `export.excel` | openpyxl export |

> `PUT /api/bom/{id}` dual-mode (memory: `reference_bom_put_permission`): `set(body.keys()) <= {"variable_value","unit_price_override"}` ⇒ `require_user`; else `require_admin`. Lets non-admin estimators persist insulation thickness + per-row price overrides; everything structural stays admin-only. API auth must raise **401 JSON**, not a 303 redirect, or `fetch().json()` breaks (memory: `feedback_api_auth_redirect`).

## C.3 Revision / version logic — **the falsy-zero trap**

`version` is stored **inside the `result_json` JSON blob**, not a column.

| Stored | Meaning | Display |
|---|---|---|
| `0` | Original quote | **no badge** |
| `1` | First revision | `Rev1` |
| `2` | Second revision | `Rev2` |

**Rules a porter MUST preserve:**
- Read with nullish-coalescing, **never `||`** (0 is falsy): `editingVersion = payload.version ?? 0` (`calculator.js:1877`).
- Display checks use `> 0`: `version > 0 ? 'Rev'+version : 'Original'` (`calculator.js:4422-4423, 4488, 1886`).
- Backend: `/api/check-duplicate` parses version + returns `max_version/next_version` (`calculator.py:683-686`); `/api/approve` sets `version=0` for a fresh quote, `next_version` for new_version, or reads existing for overwrite (`calculator.py:817-860`).
- Edit-save modal labels are contextual: editing original → "Overwrite original" + "Save as new Revision 1"; editing Rev1 → "Overwrite Rev1" + "Save as new Revision 2".
- **Data migration** (decrement every historical `version` by 1) — PostgreSQL SQL is in the [BA briefing §4 Change B](BA_RELEASE_BRIEFING_2026-06-19.md). **Run once, after deploying the code.**

## C.4 Configuration Summary (right-click Body Options)

- `showParamsSummary()` (`calculator.js:6285`) → `_buildParamsSummaryHTML()` (`6296-6357`) reads `window.calcAutoFix.getInsulationState()` + `getBodyOptionState()`.
- Context menu wired by `_initParamsCtxMenu()` IIFE (`6250-6283`) on `#body-options-section`; closes on Esc/click-outside.
- Modal `#modal-params-summary` (body `#params-summary-body`). CSS: `.ps-section`, `.ps-dims`, `.ps-ins-table`, `.badge-eps` (blue `#60a5fa`/`#1e3658`), `.badge-pu` (green `#4ade80`/`#163a26`).
- **Native React port required; iframe path closed** (22 Jun decision — see Part C header). `LiveCalculator.tsx` is retired, so this modal does **not** come free — re-implement `showParamsSummary` / `_buildParamsSummaryHTML` as a React component that reads the native calculator's insulation + body-option state, and re-create the `.badge-eps` / `.badge-pu` styling.

## C.5 PDF export & static cache-busting

- `GET /results/{id}/export/pdf` → `user_can(user,"export.pdf")` → render `cost_breakdown.html` → `weasyprint.HTML(string=...).write_pdf()` (`exports.py:498-499`). Context vars listed in the agent map (trailer_name, dims, items[], category_totals, optional_cats, margins, discount_*, net_total, …).
- **Cache-busting is manual `?v=N`**: `calculator.js?v=125` (`calculator.html`), `style.css?v=17` (`base.html:8`). Bump on every edit or clients keep the stale file (memory: `feedback_bump_static_version`). N/A once ported to React's hashed bundles.

## C.6 Port caveats (C → React/Postgres)

- `result_json`/`dimensions_json` are `Text().with_variant(LONGTEXT(),"mysql")` (`database.py:10`). On Postgres use **`JSONB`**; SQLAlchemy ORM otherwise unchanged.
- **Keep the calc engine on the backend.** `_build_bom_items()` (`calculator.py:150-458`) is 300+ lines of body-option gating — re-call the backend from React, don't re-derive in TS.
- **Keep Jinja for the PDF.** Easiest path: React calls `GET /results/{id}/export/pdf`; FastAPI keeps `cost_breakdown.html` + WeasyPrint. (See Part D for the WeasyPrint landmine.)
- Browsers flatten nested `<tbody>` — collapsible groups use `data-grp` row attrs, not nested tbody (memory: `feedback_nested_tbody`). Becomes component state in React.
- No native `alert/prompt/confirm` in GRP (memory: `feedback_no_native_dialogs`) — use the app modal helpers; in React use the MES modal system.

---

# Part D — Cross-cutting dependencies, environment & the WeasyPrint/Pango landmine

## D.1 Python dependencies (source app)

`anthropic>=0.40` · `sse-starlette>=1.6,<2.0` · `openpyxl>=3.1` · `weasyprint==52.5` · `reportlab>=4.0` · `pypdf>=4.0` · `pillow>=10.0` · `svglib>=1.5` (root `requirements.txt`). MES Postgres swaps `PyMySQL` → `psycopg2`/`asyncpg`.

## D.2 Environment / secrets

| Var | Needed by | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | Help assistant | No key ⇒ Help button hidden, `/chat` 503. **Not needed** for calculator/audit-math |
| `ANTHROPIC_HELP_MODEL` | Help (optional) | Overrides default Haiku |
| `DATABASE_URL` | all | GRP prod MySQL; dev SQLite/local MySQL; MES = Postgres |

## D.3 🔴 WeasyPrint ↔ Pango landmine (just debugged — read before touching PDF)

**Symptom (prod):** `PDF generation failed: ... undefined symbol: pango_context_set_round_glyph_positions`.
**Cause:** WeasyPrint **53+** calls a Pango symbol that only exists in **Pango ≥ 1.44**. The GRP prod host (cPanel/RHEL 8) ships **Pango 1.42**. WeasyPrint must stay at **52.5**.

- The GRP deploy installs from **`app/requirements.txt`** (`.cpanel.yml` → `pip install -r app/requirements.txt`) — **not** the root `requirements.txt`. The two files had **drifted** (root `52.5`, app `65.1`); the app file won and broke prod. **Fix (`a077987`):** both now pinned `52.5`. **Lesson for the MES:** keep one requirements source, or assert the WeasyPrint pin in CI.
- **Dev (Windows):** `import weasyprint` needs the **GTK3 runtime** native DLLs (Pango/Cairo/GObject). This box has `C:\Program Files\GTK3-Runtime Win64\bin` on PATH; `pip install weasyprint==52.5` into `.venv` then renders fine (verified: `GET /results/41/export/pdf` → 200, 136 KB `%PDF-1.5`).
- **MES (Postgres/Linux) — Pango = ⏳ TBC (not yet confirmed):** the MES prod box (`192.168.0.251`, Ubuntu 24.04 "Noble") could **not** be reached from the authoring machine on 2026-06-23 — off the office 192.168.0.x LAN with no VPN, so TCP `:22` timed out. **Prediction:** Noble ships Pango **~1.52/1.54**, so v4.38 + v4.37 can almost certainly use a **current WeasyPrint** with **no 52.5 pin** — UNCONFIRMED. **Confirm from the office LAN/VPN** with `ssh icb@192.168.0.251 'pkg-config --modversion pango'`: if ≥1.44 → current WeasyPrint is fine; if 1.42 → apply the same `==52.5` pin + GTK caveat above. *(Flip this line to CONFIRMED once checked.)*

## D.4 Deploy mechanics (GRP, for reference)

cPanel Git Version Control runs `.cpanel.yml` (pip install + `touch tmp/restart.txt`). `~/icecoldgrp` is **not** a git repo — don't `ssh + git pull` (memory: `reference_prod_ssh`). New tables need manual `create_all` via cPanel Terminal (memory: `feedback_prod_new_tables_manual`). Always commit every file `main.py` imports or you get a 502 (memory: `feedback_commit_all_imports`).

---

# Part E — Prompts debugged (consolidated)

Three "prompt assets" matter for the port:

### E.1 Help system prompt (PERSONA) — `app/help/prompts.py:23-109`
The behavioural contract (rules 1–15) covering: no-code-disclosure, read-only, permission relay, reconciliation-citation discipline (quote deltas verbatim, separate rounding noise, quote both `excel_formula`/`app_formula`), insulation-first diagnosis, the **mandatory `propose_actions` call when `suggest_actions=true`**, section-investigate formatting, and Auto-Update run-summary narration. **Treat `prompts.py` as canonical — re-export from source at port time**, then re-map the action/nav allowlist to MES routes (see A.6). The full current text is reproduced verbatim in the appendix block below for review.

### E.2 Auto-Update narration rules — `app/help/prompts.py:89-104`
"Investigate the **<SECTION>**…" and "Auto Update run summary: <JSON>" formats. These are *narration-only*; the numbers come from the deterministic engine (Part B). Keep the "quote verbatim, never recompute, <200 words" discipline.

### E.3 Code-Agent execution prompt — **already written** in [`BA_RELEASE_BRIEFING_2026-06-19.md` §4](BA_RELEASE_BRIEFING_2026-06-19.md)
A ready-to-paste prompt for the MES Code Agent covering revision semantics, the PostgreSQL migration SQL, the edit-save modal, and the Configuration Summary. **CA4/v4.37-CA: start from that prompt, use this inventory as the file map.**

> **Appendix — verbatim PERSONA** (copy from `app/help/prompts.py:23-109` at port time; reproduced for review):
>
> ```
> You are the in-app Help assistant for the GRP Costings System — a trailer-body costing and BOM management web app built for IceCold.
>
> You help end users (sales, costing admins, factory admins) understand how to use the app, explain how data and pricing flow through it, and answer questions about the actual costing/BOM/materials data they can see.
>
> Rules you MUST follow:
>
> 1. Never reveal information about the code or implementation. (No file names/paths/modules, function/class/table/column names, routes/URLs/endpoints, framework/library names, or code snippets. Explain business data-flow only; decline "how is this implemented / what's the schema / show me the code / what's the endpoint".)
> 2. Stay focused on this app; decline unrelated topics.
> 3. Be concise (2–5 sentences for "how do I"; bullets for multi-step).
> 4. Point to exact menu paths using on-screen labels.
> 5. For data questions, read attached page context first, else call a tool; never speculate when you can look it up.
> 6. Permissions are enforced automatically; relay denials briefly.
> 7. NEVER look up or discuss users, passwords, sessions, login activity, or permission assignments — off-limits to everyone incl. admins.
> 8. You are read-only; explain steps instead of doing changes.
> 9. Currency = ZAR (R); dimensions in metres.
> 10. Don't invent menus/screens/permissions/features.
> 11. When a <reconciliation> block is present, treat it as source of truth; quote deltas verbatim; lead with grand-total delta, then biggest sections, then lines; surface warnings first; if live_grand_total is null, tell them to run the calculator. (Section-presence, multipliers-already-applied, per-line cause objects with excel_formula/app_formula, rounding_drift_total, insulation-first, option_flags, and "offer Auto Update on real non-rounding diffs" rules all spelled out here.)
> 12. If the reconciliation block has an error key: sheet_not_found → list available_sheets verbatim and suggest the match; parse_failed/workbook_unreadable → apologise, ask for re-export.
> 13. propose_actions tool: if page_context.suggest_actions is true you MUST call it at the end of every substantive reply; 1–4 buttons; don't mention them in text. Allowed types: highlight_bom_lines, highlight_element, scroll_to, navigate, auto_update_costing. Allowed targets and nav paths are fixed allowlists.
> 14. Investigate-section requests: opening sentence with total delta, 3–5 root-cause bullets biggest-first, closing unaccounted-variance line; cite every number; <200 words.
> 15. Auto Update run summaries: lead with balanced/Δ, list insulation + price changes, explain skipped items, mention ignored_rounding, remind Undo; quote numbers verbatim; <200 words.
> ```
> *(Rules 11/13 are abbreviated above for readability — the source file carries the full multi-paragraph text incl. all examples; port from source.)*

---

# Part F — Port verification checklist & open items

**AI (CA4 / v4.38):**
- [ ] `anthropic` SDK + `ANTHROPIC_API_KEY` wired; `/health` returns `configured:true`
- [ ] System prompt ported from `prompts.py`; **action/nav allowlist re-mapped to MES routes**
- [ ] 8 read-only tools re-implemented with `user_can()` gating + `redact()`
- [ ] `help_request_log` table **explicitly created** in the Postgres migration (don't trust `create_all`)
- [ ] Reconcile + autofix ported as **deterministic** logic (no LLM); all 6 Excel landmines (B.4) preserved
- [ ] `bom.auto_update` permission seeded for `{admin,full,user}`
- [ ] MES-specific `app_guide.md` written (GRP guide describes GRP menus)

**Calculator (v4.37 CA):**
- [ ] `version` semantics: `?? 0` not `|| `, `> 0` display, fresh quote = 0
- [ ] PostgreSQL version-decrement migration run **once, after deploy** (BA briefing §4-B)
- [ ] `result_json`/`dimensions_json` → `JSONB`
- [ ] `PUT /api/bom/{id}` dual-mode + **401-JSON** (not 303) on API auth
- [ ] PDF: confirm host **Pango version** before choosing the WeasyPrint pin (D.3)

**Open items / unknowns (status @ 2026-06-23):**
- ✅ **RESOLVED — calculator architecture:** independent **native React** Cost Calculator (22 Jun PM, v4.37 Q1 = Option A). GRP iframe retired; AI features in v4.37 core scope. Part C.4 must be re-implemented (no free iframe features).
- 🟡 **PARTIAL — `navigate`/`highlight_element` allowlist:** not blocking for **v4.38** (Feedback Portal doesn't navigate users). The **v4.37 CA finalizes** it against the then-current MES routes; a starting route surface is documented in **§A.6.1**.
- ⏳ **TBC — MES host Pango version:** couldn't reach `192.168.0.251` from the authoring machine (off office LAN/VPN). Predicted current (Noble ~1.52/1.54) → likely no pin needed, but **run the §D.3 check from the office LAN** and confirm before v4.38/v4.37 PDF work.

---

*Source commit `a077987` on `main`. Cross-refs: [BA briefing](BA_RELEASE_BRIEFING_2026-06-19.md), `DEPLOYMENT_TROUBLESHOOTING.md`, `PDF_TEMPLATES_README.md`. Generated for the CA3 stand-down handoff, 2026-06-23.*

*Rev 2026-06-23 PM: incorporated the v4.37 native-React decision (GRP iframe retired — §C, §C.4), documented the current MES route surface (§A.6.1) for the v4.37 `navigate` allowlist, and recorded the MES-server Pango version as TBC (§D.3) pending office-LAN access.*
