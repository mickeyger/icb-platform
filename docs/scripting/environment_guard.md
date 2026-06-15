# Script environment guard (WO v4.34.4 §3.2)

Every DB-mutating maintenance script in `backend/scripts/` routes through a guard at its entry point
(`backend/scripts/_environment_guard.py`, a thin wrapper over `backend/app/db_guard.py`). The guard is
keyed on the **database name**, not the hostname — the dev DB (`icb`), every `*_test` DB, and CI all
live on `localhost`, so only the name discriminates. This is the v4.27 rule ("never run destructive ops
against the shared dev DB") turned into code, after a script-driven re-seed contaminated `icb` in the
14–15 June 2026 session.

## The three tiers

| Tier | Function | Behaviour on shared dev DB (`icb`) | Behaviour on `*_test` DB |
|------|----------|-------------------------------------|--------------------------|
| 1 — full-wipe / reconcile | `require_test_db(context)` | **HARD REFUSE** (raises; no override) | proceed |
| 2 — scoped-destructive | `confirm_if_shared_db(context, destroys=…)` | require confirmation (env var or interactive `y`); else **refuse** | proceed |
| 3 — additive / idempotent | `announce_target(context)` | announce target + proceed | announce + proceed |

**Tier 2 confirmation** is satisfied by either an interactive `y` at the prompt, or setting
`ICB_ALLOW_SHARED_DB_WRITE=1` in the environment for a deliberate, non-interactive dev-DB run. With
neither (e.g. piped/CI), it **fails safe** and refuses — it never silently proceeds.

**Tier 2 audit trail.** The middle tier is the residual risk surface (a fat-finger `y`, or a stale
`ICB_ALLOW_SHARED_DB_WRITE=1` left in a shell). Every Tier-2 confirm that *allows* a scoped-destructive
op against a non-test DB appends one tab-delimited line to `backend/scripts_audit.log` (gitignored
`*.log` — an operational trail, not a committed artifact): UTC timestamp, operator (`getpass.getuser`),
script, `mode` (`env`/`interactive`), the `ICB_ALLOW_SHARED_DB_WRITE` value, `argv`, and the target
`host=…/db=…`. Logging is best-effort — a write failure warns but never blocks the operation. (Tier-1
refusals and Tier-3 announces are not logged; a refusal is already loud, and Tier 3 is non-destructive.)

There is **no override for tier 1.** A TRUNCATE-all or a calc/job reconcile can only ever run against a
`*_test` database. To run one, point `DATABASE_URL` at your test DB (see [docs/testing/setup.md](../testing/setup.md)).

## Per-script assignment

**Tier 1 — HARD-refuse unless `*_test`** (full wipe or reconcile):

| Script | Why |
|--------|-----|
| `seed_from_mockup.py` (`_truncate_mes`) | `TRUNCATE icb_mes.* RESTART IDENTITY CASCADE` (+ icb_sap landing). The original contamination vector. Guarded at the TRUNCATE itself, so a fresh-empty seed into a new DB still works. |
| `import_workbook.py` (`_truncate`) | one-shot `TRUNCATE icb_mes.*` + reload from the production workbooks. |
| `backfill_prejob_calc_status.py` | reconciler — advances `calculations.status`/`production_jobs.status`. "No reconcile scripts on the shared dev DB." Gated even for `--dry-run`. |
| `backfill_prejob_job_anchor.py` | reconciler — creates anchor jobs for carded calcs. Gated at `main()` only, so the in-seed `ensure_jobs_for_carded_calcs(db)` call is unaffected. |

**Tier 2 — confirm on shared dev DB** (delete-a-slice-then-reinsert / CASCADE re-import / in-place rewrite):

| Script | What it deletes/rewrites |
|--------|--------------------------|
| `seed_v4_25_rules.py` | DELETE Freezer/Vacuum BOM rules + lookups for the section, re-insert |
| `seed_v4_26_spec_options.py` | DELETE Vacuum Materials spec options, re-insert |
| `seed_v4_27_body_geometry.py` | DELETE each body type's Vacuum rules + lookups, re-insert |
| `seed_v4_28_chassis_mock.py` | DELETE `source='mock'` chassis, re-insert (CLI entry only; the in-seed call is unaffected) |
| `translate_chassis_register.py` | DELETE `source='register'` chassis + CASCADE events + photos, re-import |
| `import_inventory_to_sap_mock.py` | UPSERT + soft-delete the `icb_sap` mock (OITM/OITW/OWHS) |
| `normalize_template_tokens.py` | UPDATE Pre-Job template tokens in place (real-write path only; `--dry-run` rolls back) |

**Tier 3 — announce only** (additive / insert-when-absent):

`seed_dealers.py`, `seed_fridge_units.py`, `seed_medical_waste_template.py`, `import_prejob_templates.py`.

## Adding a new mutating script

Call exactly one guard at the entry point, chosen by blast radius:

```python
from scripts._environment_guard import require_test_db        # full wipe / reconcile
from scripts._environment_guard import confirm_if_shared_db   # scoped delete / cascade / in-place rewrite
from scripts._environment_guard import announce_target        # additive / idempotent
```

Guard the **CLI entry** (`main()` / `__main__`), not the reusable function, so the script can still be
composed internally (e.g. `seed_from_mockup` calling `ensure_jobs_for_carded_calcs`) — unless the
destructive statement itself is the right granularity (as with the two TRUNCATE helpers).
