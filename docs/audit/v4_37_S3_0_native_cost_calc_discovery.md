# v4.37 Native Cost Calculator (MVP) — §3.0 Discovery & Reuse Map

> **Status:** Discovery complete (3-subagent fan-out per §0.7). **NO feature code, NO alembic authored/applied.**
> §3.1 build is gated on BA ratification of the refined scope + the Open Asks (§10) below.
> This is the formal §3.0 artifact (kickoff §0.8 location corrected — see §8 D-0).
>
> **Author:** CA5 (v4.37 Native Cost Calculator). **Base:** `feat/v4.37-native-cost-calc` @ `5029a24` (= `origin/main`, v4.36b.2 #51).
> **Companions:** [`../handoffs/CA3_GRP_AI_Port_Inventory.md`](../handoffs/CA3_GRP_AI_Port_Inventory.md) (port source-map) · [`v4_38_S3_0_feedback_portal_discovery.md`](v4_38_S3_0_feedback_portal_discovery.md) (CA4 sibling — AI-infra-already-native headline) · outline `ICB_MES_WorkOrder_v4.37_NativeCostCalculator_OUTLINE.md`.

---

## 0. Headline — three premise corrections that re-shape the sprint

The kickoff/outline frame v4.37 as *"build a native React Cost Calculator backend + frontend, then retire a faje.co.za iframe."* Code at HEAD says otherwise on all three axes:

1. **The calculator BACKEND is already 100% native and production-running in icb-platform.** `backend/app/routers/calculator.py` (1192 ln) is a full native engine — every GRP endpoint (`/api/calculate`, `/api/approve`, `/api/check-duplicate`, `/api/calculations` + `/accept` `/decline` `/{id}` DELETE), a native formula engine (`formula_engine.py`), BOM/cost services (`services/__init__.py`), idempotent quote numbering (`quote_numbering.py`), discount logic (`calculator.py:548-571`), and PDF/Excel export (`exports.py`). **No proxy/forward to GRP** (zero `httpx`/`requests`/`faje` hits in `calculator.py`). **⇒ v4.37 is a FRONTEND-heavy sprint, not backend+frontend.** The outline's "~50-60 days CA1 work for the calculator core" backend estimate is largely already spent.

2. **The iframe is NOT faje.co.za — it is a same-origin in-repo Jinja fork.** `LiveCalculator.tsx:10` → `const TARGET_URL = '/mes/calculator'`, served by icb-platform itself at `backend/app/routers/mes_views.py:34-42` (the cross-domain GRP embed was retired back in WO v4.7, per the component's own comment at `LiveCalculator.tsx:6-9`). **⇒ "iframe retirement" (§3.5) is an internal Jinja-fork delete, not a cross-domain decommission.** No `faje.co.za` exists in any runtime code path (only in `tools/`, `*.sql`, README/CHANGELOG, comments). The faje.co.za hosting/repo archival (outline Q11) is a *separate, non-code* concern.

3. **The migration projection is wrong, and v4.37 very likely needs NO migration.** Alembic chain is clean linear `0001→0027_feedback_submissions`, single head **0027**. There is **no 0028 (v4.36c) or 0029 (v4.36.5)** on this base — the kickoff's "0030" assumes two unlanded sprints. Discount columns already exist (`0015`), `version` lives inside `result_json` (not a column), `result_json`/`dimensions_json` already exist. **⇒ Plan for ZERO new schema; author against the real `alembic heads` at author-time only if a need emerges.**

**Net:** the heavy lifting is (a) the native React calculator UI (replacing the `/mes/calculator` iframe), (b) AI **allowlist re-map + calculator persona** (reusing in-repo `app/help/`), (c) the **one genuinely greenfield backend item — Auto-Update** (absent in icb today), and (d) a small backend **hardening** pass (security/concurrency/validation surfaced by the adversarial review). This is *more achievable* than the kickoff implied on backend, but the AI "reuse" framing hides one real build (Auto-Update) and a set of decisions that gate the parallel-run.

---

## 1. Workspace & branch provenance

| Item | Value |
|---|---|
| Worktree | `C:/Users/micge/Documents/icb-platform-v4.37` (git worktree; object store shared with primary clone) |
| Branch | `feat/v4.37-native-cost-calc`, off `origin/main` @ `5029a24` ("v4.36b.2 … #51") |
| Remote | `origin = https://github.com/mickeyger/icb-platform.git` ✓ (working repo per kickoff banner) |
| Sibling worktrees | `…/icb-platform` (CA1, `feat/v4.36b.2-csrf-middleware`) · `…/icb-platform-v4.38` (CA4, `feat/v4.38-feedback-portal`) — **untouched** |
| Dev server port | **8000 free?** — CA1 historically owns 8000, CA4 owns 8001. v4.37 should claim **8002** to avoid collision (confirm at §3.2). |
| Installs | **Deferred to §3.1** (read-only discovery needs none). NOTE: kickoff's `npm install` at repo root is wrong — `package.json` is at `frontend/package.json`; pip venv convention unconfirmed (see §10 D-7 note). |

**Non-negotiable constraints carried in (outline §4 + kickoff §0):** `/calculator` + `/calculator2` (Jinja) byte-identical · `icb_sap.*` READ-ONLY (ADR 0013) · `ICB_ALLOW_SHARED_DB_WRITE=0` in prod · v4.34.4 invariants held · React renders on `/mes-app/*` only · no prod deploy/migration without BA · `chassis_records` read-only for v4.37 (§0.20, coordinate w/ CA4 v4.36.5).

---

## 2. Integration points (verified at HEAD in this worktree)

| Concern | Finding | Evidence |
|---|---|---|
| **Calc backend** | Full native engine, no proxy. `/api/calculate`, `/api/approve`, `/api/check-duplicate`, `/api/calculations`(+detail/accept/decline/delete). | `routers/calculator.py:576,665,710,970,1130,1064,1092,1118` |
| **Formula engine** | Native safe-eval (`__builtins__:{}` sandbox + math allowlist). | `formula_engine.py:95`, `:141-223` |
| **Model** | `CalculationRecord`, table `icb_costings.calculations`. `version` is **NOT a column** — read from `result_json`. | `database.py:405-476`; `calculator.py:683` |
| **Discounts** | `discount_kind/_input/_amount/net_total` columns (0015) written + read; bounded clamps. | `0015_calc_discount_columns.py:17-20`; `calculator.py:548-571,823-826,870-873,1004,1184-1187` |
| **PDF/Excel** | icb canonical path = **reportlab/pypdf** (not WeasyPrint). A legacy WeasyPrint route may still exist in `exports.py`. | `requirements.txt:7,41-44`; `exports.py:433-513` |
| **AI infra** | Native `AsyncAnthropic` assistant — Haiku `claude-haiku-4-5-20251001`, buffered-SSE, 30/hr rate-limit, `help_request_log` telemetry, 8 read-only redacted tools, `propose_actions` allowlist. | `routers/help.py`; `help/__init__.py:41,48`; `help/tools.py:404-469`; `database.py:922-941` |
| **AI SDK** | `anthropic==0.104.1`, `sse-starlette==1.8.2` already present. | `requirements.txt:52,16` |
| **Excel Audit (reconcile)** | Present + working (`/api/help/audit`). **Auto-Update/autofix is ABSENT** (no `autofix.py`, no `/auto-fix/*`). | `help/reconcile.py`; `help.py:541`; (grep `autofix`/`auto-fix` = 0 backend hits) |
| **Iframe wrapper** | `LiveCalculator.tsx` embeds same-origin `/mes/calculator`; mounts at `/costings/new`. | `LiveCalculator.tsx:10,69-76`; `App.tsx:29` |
| **MES Jinja fork** | `/mes/calculator` served by `mes_views.py:34-42`, registered `main.py:91,183`; vite `/mes` proxy. | `mes_views.py:34`; `main.py:91,183`; `vite.config.ts` |
| **React routes** | `/costings`, `/costings/new`, `/costings/:quote`, `/costings/new-mock`, … under base `/mes-app/`. | `App.tsx:25-56` |
| **propose_actions allowlist** | `ALLOWED_PATHS` is **Jinja-only** (`/calculator`, `/admin/materials`, …), **zero `/mes-app/*`**. | `tools.py:412-417` |

---

## 3. Scope re-shape — already-built vs v4.37-builds

| Capability | Status in icb today | v4.37 work |
|---|---|---|
| Calc engine + endpoints | ✅ native, complete | **none** (reuse) |
| Persistence / approve / quote# | ✅ native, complete | **none** (reuse) |
| Discount calc + columns | ✅ native (0015 wired backend; partial React) | wire React (`discount_kind` dead, `net_total` absent from React iface) |
| PDF/Excel export | ✅ reportlab/pypdf native | confirm canonical path; retire dead WeasyPrint route (D-7) |
| AI Help assistant infra | ✅ native (`app/help/`) | **re-map allowlist to React routes** + calculator persona + MES `app_guide.md` |
| Excel Audit (reconcile) | ✅ native (`/api/help/audit`) | wire React audit panel UI |
| **Auto-Update Costing** | ❌ **absent** (greenfield) | **build** `autofix.py` + `/auto-fix/plan\|apply-prices\|apply-formulas` + React loop, with propose-only/validated-formula discipline |
| Native React calculator UI | ❌ iframe today | **build** (the bulk): body-type, dims, insulation EPS/PU, body options, cost summary, BOM display/edit, optional extras, live recalc |
| Revision/duplicate UX (React) | ❌ GRP-Jinja-only | **build fresh** (duplicate-warning modal, contextual edit-save labels, version badges) |
| Config Summary modal (C.4) | ❌ iframe path closed | **build** React component |
| Iframe / `/mes/calculator` fork | live | **retire** (§3.5) |

---

## 4. Reuse map — mirror / extend / build-new

**MIRROR (reuse as-is from `app/help/`):** model config + `is_configured()` env gate (`__init__.py:41,48`), buffered-SSE shape (`help.py:517-537`), 30/hr rate-limit (`help.py:40,44-55`), `_persist_log()`/`HelpRequestLog` telemetry (`help.py:114-138`), `redact.py`, persona/cache-block scaffolding (`prompts.py`), the 8-tool `user_can()`+`redact()` pattern, **the `validate_actions` server-side allowlist enforcer** (`tools.py:404-469` — this is the real injection gate; keep verbatim).

**EXTEND:** new calculator-specific AI tools + costing-Q&A persona; **rewrite `ALLOWED_PATHS`/`ALLOWED_TARGETS`** (`tools.py:407-417`) to the React surface (the A.6.1 finalization v4.37 owns); MES-specific `app_guide.md` (current one is GRP-menu-specific); wire the existing reconcile engine to a React audit panel.

**BUILD NEW:** the native React calculator UI (the bulk); Auto-Update backend (`autofix.py` + `/auto-fix/*`) + client loop — **greenfield, NOT a port** (D-6); the React revision/duplicate UX; the Config Summary modal.

**EXPLICITLY NOT NEEDED:** new schema (§0/§5); WeasyPrint/Pango handling if reportlab is canonical (D-7); cross-domain/CSP work (iframe is same-origin).

---

## 5. ⚠ Alembic coordination (cross-CA)

- **Head on this base = `0027_feedback_submissions`** (`down_revision="0026"`), single linear chain `0001→0027`, no multi-head. v4.36b (`0026`) + v4.38 feedback (`0027`) have both landed on main since CA4's discovery (which saw `0025`).
- **No `0028`/`0029` exist.** Kickoff's "0030" is a projection assuming v4.36c (0028) + v4.36.5 (0029) land first — they have **not** on this base.
- **Rule:** v4.37 plans **zero migrations**. If one becomes necessary (e.g. the version-decrement backfill under D-2), author it against the **real** `alembic heads` at author-time and surface to BA before applying (§0.2). Do **not** hardcode 0028/0030 — v4.36c/v4.36.5 may take them first; rebase `down_revision` onto the real head (the exact pattern `0027`'s header documents).
- **§0.12 smoke-bump:** N/A unless v4.37 introduces new `Base.metadata` models (it does not, on current plan).

---

## 6. Adversarial review (Subagent B) — findings

> Distinguishes **today-risk** (live in code) from **build-risk** (v4.37 must avoid). Severity: BLOCKER/MAJOR/MINOR.

| # | Finding | Sev | When | Evidence | Mitigation (§3.x) |
|---|---|---|---|---|---|
| B1 | **No IDOR/branch scoping** on `/api/calculations/{id}` get/edit/accept/decline/export — any authed user touches any branch's quote by id (`branch_id` exists, never filtered). DELETE is correctly admin-only. | MAJOR | today | `calculator.py:804,921,1070,1097,1135`; `exports.py:441,525`; model `database.py:408` | **Decision (D-3)**: open-by-design (ADR) vs scope by `active_branch`. Settle before parallel-run. |
| B2 | **No optimistic locking** on overwrite/approve — last-write-wins; only guard is status≠pending 409; `_approve_lock` is process-local. | MAJOR | today | `calculator.py:798,803-834` | **D-4**: `updated_at`/version etag → 412 on mismatch. |
| B3 | **BOM PUT user-mode allowlist = `{variable_value}` only**, omits `unit_price_override` — contradicts CA3 §C.2 + WO. Non-admin price overrides are admin-blocked (fail-safe, but the React override UI will 403). No smuggling risk (strict-subset check). | MAJOR | today | `trailers.py:280` | **D-5**: resolve doc-vs-code contract before building React BOM-edit UI. |
| B4 | Calc engine does **no input-range validation** — negative/zero/absurd dims flow through; floored at 0 so no crash, but silently-wrong R-values, no error surfaced. | MINOR | build | `formula_engine.py:96,179-180`; `calculator.py:515-543` | Validate dims>0/within max at React **and** `/api/calculate` → 400, don't emit silently-wrong totals. |
| B5 | **Reconciliation report not redacted** — `/audit` emits raw `unit_price`/`total`/grand-total gated only by `bom.view_prices`; `bom.view_full_cost` distinction collapsed. | MINOR | today | `reconcile.py:296,340,397-415`; `help.py:504,589` | **D-9**: run report through `redact()` OR document that `view_prices` implies totals in reconcile. |
| ✅ B6 | **Action allowlist IS enforced server-side** (`validate_actions`) — prompt injection in `page_context`/`reconciliation` cannot navigate off-allowlist; worst case = rejected/whitelisted nav. | SAFE | — | `tools.py:404-469`; `help.py:248-258` | Preserve verbatim; re-map paths in lockstep. |
| ✅ B7 | **API auth returns 401 JSON** on `/api/*` (not 303) — `feedback_api_auth_redirect` satisfied. | SAFE | — | `deps.py:71-73` | Keep 401 branch for React fetch endpoints. |
| ✅ B8 | **Discount logic well-bounded** — % clamped 0–100, amount clamped to base, `net_total` floored. No stacking. | SAFE | — | `calculator.py:548-571` | Port clamps as-is. |
| ✅ B9 | `eval()` formula engine is sandboxed (`__builtins__:{}`), client-reachable via `formula_overrides` but blocks imports/dunder escapes (accepted GRP pattern). | SAFE* | today | `calculator.py:236,289,620,752`→`formula_engine.py:95` | Acceptable; optional hardening = route via AST evaluator. Not a v4.37 regression. |
| B10 | **AI hallucination cannot reach DB today** — no apply path exists. When Auto-Update is built, propose-only + `evaluate_formula`-validation discipline (CA3 §B.2) is **NOT yet enforced anywhere** and must be (re)built + tested. | build | — | (no `autofix.py`) | **D-6**: enforce in code + unit test, don't rely on the doc. |

---

## 7. Silent-deferral + premise-vs-predicate (Subagent C)

### 7a. Silent-deferral (ADR 0026 H6 lens) — the one in v4.37's lane

- **`calculator.py:899-902` (CRITICAL for v4.37):** `assign_quote_number()` is wrapped `try/except: logging.exception(...)` then falls through to `db.commit()` — a save where numbering throws **still persists with `quote_number=NULL` and returns 200**. This is the in-calculator instance of the v4.36a.4 silent-deferral lesson. **v4.37 must surface this (explicit error / RED-flag), not log-and-commit.**
- Adjacent (not calc-core, but the *validator travels into v4.37's AI port):* `help.py:256` + `tools.py validate_actions` — a rejected `propose_actions` emits **no client event** (text reply, zero buttons, server-log only). When porting AI action buttons, emit a reason/`error` SSE event. Also `PreJobCardModal.tsx:286` save-then-`if(!saved) return` (button can hang; the React calc's save/approve handlers must block progression + reset busy state, not silently advance).

### 7b. Premise-vs-predicate (§0.14)

| Item | Predicate | Premise (real consumer?) | v4.37 implication |
|---|---|---|---|
| **Version `?? 0`/`>0`** | ❌ icb is **1-based** today (`\|\| 1`), not the doc's `?? 0`. The 0-based scheme is the **GRP target**, unimplemented in icb; doc line cites are stale. | `version` stored in `result_json`, not a column (`calculator.py:683,817,856,858`). **No React consumer** implements it. | **Build 0-based fresh in React** (`?? 0` never `\|\|`, display `>0`). Adopting 0-based ⇒ one-shot result_json backfill (**D-2**). |
| **Discount cols (0015)** | ✅ correct | ✅ **NOT orphaned** — written + read backend; `CostingDetail.tsx:170-173` renders `discount_amount`. *But* `discount_kind` never rendered in React; `net_total` absent from React iface. | **Wire-existing-dormant**, not build-from-scratch. Light up `discount_kind`/`net_total` in React. |
| **BOM dual-mode** | ⚠ code allows `{variable_value}` only (B3) | **No React consumer** — no PUT `/api/bom` anywhere in `frontend/src`; only legacy GRP `calculator.js` exercises it. | Decide key-set (**D-5**) + **build the non-admin BOM-edit UI fresh**. |
| **check-duplicate / quote reuse** | ✅ backend works | **No React consumer** — `next_version`/`max_version`/`parent_quote_number` absent from `frontend/src`; entire duplicate/revision UX is GRP-Jinja-only. | **Build-fresh React** duplicate-warning modal + revision-family UX. |

### 7c. Orphaned-schema sweep (0009–0027)
**None strictly orphaned** for calc/bom/cost/quote/discount. The `bom_rules`/`bom_spec_options`/`generated_boms` family (0009/0010/0011) is **live but a different subsystem** (rules-engine + production-BOM-on-accept) — v4.37's native calculator (`_build_bom_items`→`calculate_bom`) must **not** assume it feeds it. Dormant-on-the-React-side light-up candidates: `discount_kind`, `net_total`, the BOM user-mode branch, the duplicate/revision endpoints.

---

## 8. DISCREPANCIES surfaced (code-grounded corrections — §0.10)

- **D-0 — kickoff paths:** GRP inventory is at `docs/handoffs/CA3_GRP_AI_Port_Inventory.md` (not `docs/audit/GRP_AI_Port_Inventory.md`); §3.0 artifact named `v4_37_S3_0_native_cost_calc_discovery.md` (this file). CA3 inventory uses **no MUST/NICE tiers** (kickoff §0.21) — scope by outline §0.8 + Q7-9 instead.
- **D-1 — backend already built:** CA3 Part C / outline frame `calculator.py` as a port target; it is **already fully native** in icb (§0.1, §2). v4.37 backend = hardening + Auto-Update only.
- **D-2 — iframe ≠ faje.co.za:** it is same-origin `/mes/calculator` (§0.2). The "retire the cross-domain GRP iframe / decommission faje" narrative conflates an internal Jinja-fork delete (in-scope, simple) with hosting archival (out-of-band, non-code).
- **D-3 — migration "0030":** wrong; head is 0027, next 0028, and v4.37 likely needs **zero** (§5).
- **D-4 — version semantics:** icb is 1-based; CA3's 0-based `?? 0` is a target requiring a data backfill, not a code-only port (§7b).
- **D-5 — Auto-Update "reuse":** it is **greenfield** in icb (no `autofix.py`/`/auto-fix/*`) — the outline's "~3-4d reuse" framing understates it; the propose-only/validated discipline must be (re)built + tested (B10).
- **D-6 — WeasyPrint/Pango landmine (CA3 D.3):** largely **moot** — icb's canonical PDF is reportlab/pypdf (`requirements.txt:41-44`). No Pango concern unless a dead WeasyPrint route is kept alive.
- **D-7 — A.6.1 route surface ≠ real `App.tsx`:** inventory lists `/mes-app/admin/health-check`, `/admin/outstanding`, etc. that aren't discrete routes; real surface is `/admin/:resource` + `/admin/feedback`. Finalize allowlist against actual `App.tsx:25-56`.

---

## 9. Refined sprint structure (effort profile shifted backend→frontend)

| § | Phase | Kickoff est | Refined | Note |
|---|---|---|---|---|
| §3.1 | Backend **hardening + decisions** (not greenfield) | 2-3d | **~1d** | input-validation 400s (B4), quote#-NULL surface (7a), + ratify D-3/D-4/D-5; engine/endpoints already exist |
| §3.2 | **Native React calculator UI** (the bulk) | 2-3d | **~5-7d** | body/dims/insulation/options/summary/BOM/extras + live recalc against existing API; per-consumer hooks (§0.15), not a global provider |
| §3.3a | AI **reuse/extend** — allowlist re-map + calc persona + MES `app_guide.md` | (part of 2d) | **~2d** | mirror `app/help/`; finalize allowlist to React routes |
| §3.3b | AI **Auto-Update GREENFIELD** — `autofix.py` + `/auto-fix/*` + client loop | — | **~3-4d** | the hidden build (D-5); propose-only/validated discipline (B10) |
| §3.4 | Integrate native calc into CostingsDashboard + revision/duplicate UX | 1d | **~1-2d** | build-fresh React duplicate modal + version badges (7b) |
| §3.5 | Retire iframe + `/mes/calculator` Jinja fork + vite `/mes` proxy + autologin | 1d | **~0.5-1d** | simpler — internal, same-origin (D-2) |
| §3.6 | Journey tests + **perf smoke (p95 ≤ 500ms, §0.19)** | 1d | ~1d | execute on CI/icb_test per ADR 0011 |
| §3.7 | Reseed + screenshots + **BA click-through gate (§0.5)** | 0.5d | 0.5d | verify-cycle close on `icb` (§0.4), coordinate w/ CA4 |
| §3.8 | ADR + iframe-retirement documentation (§0.18) | 0.5d | 0.5d | record D-1…D-7 + decisions |

**Scope levers if August pressure bites:** defer §3.3b Auto-Update to v4.37.1 (it's greenfield, and Nadie retains it on the read-only GRP archive during parallel-run); defer the React Excel-Audit panel UI (engine already exists server-side).

---

## 10. Open asks to BA (ratify before §3.1 GO)

1. **D-3 IDOR/branch scoping (MAJOR):** quotes open-to-all-estimators (record ADR) **or** branch-scoped via `active_branch`? Needed before Simeon parallel-run. *Recommend: explicit decision, not silent default.*
2. **D-4 optimistic locking (MAJOR):** add `updated_at`/version etag → 412 on overwrite/approve? *Recommend: yes — cheap, protects parallel-run integrity.*
3. **D-5 BOM PUT allowlist (MAJOR):** enable non-admin per-row `unit_price_override` (add to `trailers.py:280`) or keep admin-only? Gates the React BOM-edit UI.
4. **D-2 version convention (Q5 follow-up):** adopt 0-based `?? 0` (requires one-shot `result_json` version backfill, Tier-2) or keep icb's current 1-based? *Recommend: adopt 0-based for data-semantic alignment, with a guarded post-deploy backfill — flagging the backfill cost.*
5. **D-6 Auto-Update scope:** confirm §3.3b (greenfield ~3-4d) stays in v4.37 core (Q9) or defers to v4.37.1. *It is NOT the "reuse" the outline implied.*
6. **D-7 PDF path:** confirm native calc targets the reportlab/pypdf path; retire the legacy WeasyPrint `/results/{id}/export/pdf` route? (Settles CA3 D.3 Pango TBC — no Pango concern if reportlab is canonical.)
7. **Calc route:** native React calc takes over `/costings/new` (retire `LiveCalculator` + `/mes/calculator`)? Confirm route naming. *Also: confirm dev-server port 8002 for v4.37.*
8. **D-9 reconcile redaction (MINOR):** `bom.view_prices` implies total-visibility in reconcile, or run `redact()` on the report?
9. **Migration:** ratify **zero new schema** for v4.37 (author against real `alembic heads` only if D-2 backfill is approved).

---

## 11. §3.0 verification checklist (click-to-verify)

- **Worktree** — `git -C C:/Users/micge/Documents/icb-platform-v4.37 status` → branch `feat/v4.37-native-cost-calc`, base `5029a24`.
- **Backend already native** — open `backend/app/routers/calculator.py` → `/api/calculate` `:576`, `/api/approve` `:710`; grep `httpx|requests|faje` in it → **0 hits**.
- **Iframe target** — `frontend/src/screens/Costings/LiveCalculator.tsx:10` → `'/mes/calculator'` (same-origin), served `backend/app/routers/mes_views.py:34`.
- **Alembic head** — `ls backend/alembic/versions | tail -1` → `0027_feedback_submissions.py`; **no 0028/0029**.
- **No new schema needed** — discount cols `0015`, `version` in `result_json` (`calculator.py:683`), `result_json`/`dimensions_json` on `CalculationRecord` (`database.py:405-476`).
- **AI infra native** — `backend/app/help/__init__.py:41` default `claude-haiku-4-5-20251001`; allowlist `backend/app/help/tools.py:412-417` is Jinja-only (the re-map target).
- **Auto-Update absent** — grep `autofix|auto-fix` in `backend/app` → **0 hits** (greenfield).
- **PDF path** — `backend/requirements.txt:41-44` reportlab/pypdf; no weasyprint pin.

**Click-to-verify — surfaces this checkpoint changed:**
- **Routes changed:** none (discovery only).
- **API endpoints added/changed:** none.
- **UI surfaces modified:** none.
- **Admin DDM screens:** none.
- **Files added:** `docs/audit/v4_37_S3_0_native_cost_calc_discovery.md` (this artifact).
- **Background actions to verify:** none. Installs (`npm`/`pip`) deferred to §3.1.

*Generated 2026-06-25 for the v4.37 §3.0 checkpoint. Reconcile against `ICB_MES_WorkOrder_v4.37_NativeCostCalculator_FORMAL.md` §0 locks when the BA files the formal WO (kickoff: drops ~7 Jul).*
