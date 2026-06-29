# ADR 0031 — Native React Cost Calculator + iframe retirement (v4.37)

- **Status:** Accepted
- **Date:** 2026-06-26
- **Work Order:** v4.37 — Native Cost Calculator MVP (Phase 1.5)
- **Builds on:** ADR 0017 (Cost Calculator cutover + parallel-codebase — v4.37 completes the *UI* half by retiring the last iframe embed), ADR 0010 (auth + active-branch — the D-3 scope), ADR 0011 (CI / `icb_test` journey execution), ADR 0026 H6 (silent-deferral on a workflow-critical path), ADR 0027 (per-consumer hooks, not a shared provider).
- **ADR numbering:** 0031 by ship-order coordination (0028 = v4.36c, 0029 = v4.36d, 0030 = v4.36.5 — all ship before v4.37 ~1 Aug). Same discipline as the Alembic chain.

## Context

ADR 0017 (v4.30) collapsed the Cost Calculator into one repo (`icb-platform`), but the MES React app still embedded it as an **iframe**: `/costings/new` rendered `LiveCalculator`, which framed the same-origin Jinja fork `/mes/calculator` (a MES-skin of the live `/calculator`, served by `routers/mes_views.py`, WO v4.7). Phase 1's "Costing-to-QC integrated end-to-end in MES" promise requires the calculator delivered **natively in React**, not via an iframe. v4.37 builds the native React Cost Calculator and retires the iframe.

§3.0 discovery (3 parallel subagents → committed artifact `docs/audit/v4_37_S3_0_native_cost_calc_discovery.md`) re-specced the kickoff premises against the real code — the load-bearing §0.10 corrections:

- The calc **backend was already 100 % native** (`routers/calculator.py` ~1192 ln, formula engine, services, quote numbering, discounts, exports — no GRP proxy). v4.37 is **frontend-heavy**, not backend+frontend.
- The iframe was **same-origin `/mes/calculator`** (the cross-domain faje.co.za embed was retired back in WO v4.7) — so "iframe retirement" is an internal Jinja-fork delete, not a cross-domain decommission.
- **Zero new schema:** the discount columns already exist (migration 0015 / ADR 0017 §4); `version` lives inside the `result_json` blob (not a column); `result_json`/`dimensions_json` already exist.
- The "GRP AI features port" + Auto-Update were **greenfield in icb, not reuse** → deferred.
- icb's PDF path is **reportlab/pypdf**, with a WeasyPrint route still live and linked from the legacy results page.

## Decisions

1. **Native React calc; same route + component name; per-consumer hooks (§0.12 / §0.15).** The native calculator lives in `frontend/src/screens/Costings/calculator/` (`CostCalculator`, `SaveBar`, `useCalculator`, `types`). It subscribes to its own data via per-consumer hooks (`useTrailers` / `useTrailerBom` / `useLiveCalc` — debounced + sequence-guarded so rapid edits never render an out-of-order total), **not** a shared `Layout.tsx` provider (the ADR 0027 pattern; zero contention with other lanes). `LiveCalculator.tsx` keeps its route (`/costings/new`) and name but its **internals are replaced** — it now renders `<CostCalculator/>` + the embedded `<CostingsDashboard/>`, no iframe. The calc only assembles inputs and renders results; the backend engine is unchanged (no new endpoints). The backend applies ratio + discount inside `/api/calculate` when sent, so the React layer reads the computed `selling_price`/`net_total` back rather than re-deriving them.

2. **Zero schema; backend stays 1-based; version displayed null-first (D-2).** icb's `version` is uniformly 1-based (fresh = 1; there is no stored `0`). The BA-ratified UX (original = no badge → ver1 → ver2; overwrite keeps the current version) is delivered as a **display-map at the React layer** (`revisionLabel`), leaving the stored values and the byte-identical legacy `/calculator` untouched and avoiding a `result_json` backfill. (A store-aligned 0-based scheme + one-shot backfill is available as a future option only if an external consumer ever needs the stored value to be null.)

3. **Backend hardening — additive, no new permission keys (§0.3).** Four §3.1 changes, no schema:
   - **D-3 IDOR / branch scope:** new calc records stamp `branch_id`; a **soft** active-branch 404-guard (ADR 0010 model + WO v4.29 D1 — NULL = shared, admin bypass) gates the by-id reads/mutations/exports; the list is soft-filtered. Scoping engages only once a branch is explicitly switched (consistent with production/planning/stock), not a hard per-user wall.
   - **D-4 optimistic lock:** `GET /api/calculations/{id}` returns a content-hash `etag`; an edit-overwrite is refused **412** on a stale token. Opt-in — the legacy Jinja calc, which sends none, is unchanged.
   - **D-5 BOM-PUT allowlist:** the user-mode set is `{variable_value, unit_price_override}` (restores the documented GRP parity; the strict-subset gate keeps structural fields admin-only).
   - **Silent-deferral fix (ADR 0026 H6):** `assign_quote_number` failure now rolls back + ERROR-logs + 500s instead of committing a `quote_number=NULL` record behind a misleading 200.

4. **Insulation thickness is a per-quote override, not a shared-template PUT.** The EPS/PU thickness goes to the engine as per-quote `body_variable_overrides` (keyed by material name; persisted in `result_json.input_state` for edit re-hydration — additive, legacy sends none) rather than `PUT`-ing `BillOfMaterial.variable_value`. This isolates one estimator's adjustment from every other estimator's open quotes (a deliberate divergence from the legacy template-mutating copy-on-switch). A **both-zero guard** blocks Save when an EPS/PU pair has no thickness on either side — the silent operator error worth a hard stop.

5. **Iframe retirement is an internal Jinja-fork delete (§3.3); the autologin seam STAYS.** `routers/mes_views.py` (both `/mes/dashboard` + `/mes/calculator`) + its templates + the Vite `/mes` proxy are deleted; `request.state.mes_skin = False` is kept (the live `/calculator` + `/` templates still read it — byte-identical preserved). **`/api/mes/autologin` is NOT removed:** code grep showed it is the **main-app dev session bootstrap** (`pre_job_card.py:390`), called on mount by every context (`AppData`, `Planning`, `Costings`, `Materials`) + the calc, and depended on by the Playwright journey harness itself. The iframe merely inherited its same-origin cookie. (The yesterday-403s seen during v4.38 debugging were its **origin gate** — `ALLOWED_ORIGINS` in `config.py:74-81`, not iframe-specificity — a config item for the deploy runbook, not a code change.)

6. **AI Help-Assistant port + Auto-Update DEFERRED to v4.37.1 (MVP discipline §0.21).** The in-repo `app/help/` AI infra is reusable, but the calculator-specific allowlist re-map and the **greenfield** Auto-Update write-loop (no `autofix.py` / `/auto-fix/*` exists in icb) are out of the MVP. Nadie retains both on the read-only GRP archive during the parallel-run.

7. **PDF: keep the WeasyPrint route; confirm + pin on the MES host (D-7).** The WeasyPrint `/results/{id}/export/pdf` route is **not dead** (it is linked from the frozen `results.html`), so it isn't retired. `weasyprint` is absent from `requirements.txt`; the host's Pango version (`pkg-config --modversion pango` on the MES VM) must be confirmed and the pin set before the deploy (reportlab/pypdf remains the degraded fallback).

8. **Tests: browser journeys are read-path, mutations are backend-tested; verify CI green per phase.** The native-calc Playwright journey (`test_cost_calc_journey.py`) asserts render only; the create→save→reopen→overwrite (412/200) lifecycle, the D-3/D-4/D-5 guards, and the p95 ≤ 500 ms perf smoke are backend tests (`test_v4_37_calc_hardening.py`). **Lesson banked** ([[feedback-verify-ci-green-each-phase]]): a frontend refactor that changes a rendered surface breaks the Playwright journeys that assert it, and `tsc -b` does not catch it — `test_costings_unified_journey` asserted the now-removed iframe and went red from §3.2 until it was updated to assert the native calc at §3.6. Confirm CI **green** (not just "pushed + tsc-clean") before each phase close, and update the asserting journey **in the same phase** that changes the surface.

## Consequences

- **The iframe era ends.** `/costings/new` is native React (create + edit-reopen + save/version + insulation EPS/PU + optional-extras + per-row overrides), driving the unchanged native backend. The `/mes/*` skin-fork surface is gone.
- **`/calculator` (Jinja) stays byte-identical** (ADR 0017 invariant held — `base.html` untouched).
- **No migration; no new permission keys; no new tables/columns** (the §0 locks held end-to-end).
- **Deferred to v4.37.1+:** the AI Help-Assistant port + Auto-Update (D-6); a store-aligned 0-based version + backfill (D-2, only if an external consumer needs it); the WeasyPrint host pin (D-7, deploy-time).
- **Ship sequencing:** PR #52 stays on its `5029a24` base; it rebases onto post-CA1-PR-#57 main (once that stabilises the `0029` chain) before the final squash-merge. The §3.7 reseed + §0.20 BA click-through on the canonical `icb` server is the deferred end-to-end live-verify — run after the rebase, on the actually-shippable state, to avoid colliding with CA1/CA4's in-flight Tier-2 work.
- **A reusable iframe→native pattern:** keep the route + component name, replace internals, per-consumer hooks; delete only the embed-specific server surface and confirm (by grep, not by name) that any "seam" you remove isn't load-bearing for the rest of the app.
