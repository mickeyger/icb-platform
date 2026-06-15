# Script archive policy (WO v4.34.4 §3.4)

`backend/scripts/` holds ~15 DB-touching maintenance scripts. Some are durable (the test/CI seed,
the catalogue seeds, the reconcilers); others were **one-shot** — a migration, a one-time data load,
or a register translation that ran once and will not run again. To keep the supported surface small
and obvious (and to keep the [environment-guard matrix](environment_guard.md) legible), retired
one-shots move to [`backend/scripts/_archive/`](../../backend/scripts/_archive/).

## What qualifies for archival

A script is a candidate when **all** hold:

1. Its job is done and will not recur (a one-time migration / load), OR it has been superseded by a
   newer script and nothing references it.
2. It is not invoked by CI (`.github/workflows/ci.yml`), by another script, or by a documented
   operator procedure.
3. Removing it from the active set does not weaken any guarantee (it carries no unique guard or
   invariant logic that lives nowhere else).

A script is **NOT** a candidate while it is still a live seeding/maintenance tool, even if version-named.

## How to archive (a deliberate, standalone change)

Archiving is its own small PR — **never** bundled into an unrelated WO, because moving a module
changes its import path (`scripts.X` → `scripts._archive.X`) and breaks any `import`/`python -m`
reference to it. The steps:

1. `git mv backend/scripts/X.py backend/scripts/_archive/X.py`.
2. Update every reference (other scripts, `.ps1` wrappers, docs, CI). If there are none, note that.
3. Drop the script's row from the [environment-guard matrix](environment_guard.md).
4. Record the move + rationale in the archiving PR description.

## Current candidates (NOT moved in v4.34.4)

Listed for a future archival pass — left in place here to avoid breaking import paths mid-WO:

| Script | Why it's a candidate | Blocker to confirm first |
|--------|----------------------|--------------------------|
| `import_workbook.py` | one-shot "Q-Ph2D-03" full TRUNCATE+reload from the production workbooks | confirm no operator runbook still calls it; `import_workbook.ps1` wrapper would move with it |
| `import_inventory_to_sap_mock.py` | WO v4.23 SAP-mock loader | `import_inventory_to_sap_mock.ps1` wrapper; confirm SAP-mock refresh isn't still done this way |
| `translate_chassis_register.py` | one-time Truck-Register → chassis_records translation | confirm the register is not re-translated on new exports |
| `migrate_catalogue.ps1` | catalogue migration wrapper | confirm superseded by the current seed path |

The version-named seeds (`seed_v4_25/26/27/28_*`) stay active: `seed_from_mockup` imports
`seed_v4_28_chassis_mock.seed_chassis_mock`, and the catalogue seeds remain the way to (re)load their
slices.
