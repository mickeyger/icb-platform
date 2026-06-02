# ADR 0007 — Seed from mockup JSON

- **Status:** Accepted
- **Date:** 2026-06-02
- **Work order:** v4.13 (Phase 2A)

## Context
Phase 2A needs realistic local data so Phase 2B (APIs) and 2C (React rewire) have
something to build against. The mockup JSON (`frontend/src/data/*.json`) is the
source of truth for that demo data. No production data is involved.

## Decision
- `backend/scripts/seed_from_mockup.py`
  (`python -m backend.scripts.seed_from_mockup [--reset]`) loads the JSON into the
  real tables.
- **The costings file drives the anchors:** `customers` + `calculations` (in
  `icb_costings`) are inserted ONLY when those tables are empty, then
  `production_jobs` links via the real cross-schema FK. The seed never TRUNCATEs
  `icb_costings`.
- **Preserve** the mockup integer IDs for `po_suggestions` (1-8), `stock_counts`
  (1-10), `discrepancies` (1-3, FK to stock_counts); assign surrogate IDs
  elsewhere and keep the business key (`quote_number`, `job_number`, `sap_code`)
  in its own column. Identity sequences are bumped after preserved-ID inserts.
- **Idempotent:** prompts before re-seeding; `--reset` is non-interactive
  (TRUNCATE `icb_mes` + re-seed) for CI.
- Tables with no JSON source (`work_orders`, `tasks`, `sign_offs`, `photos`,
  `planning_acks`) seed empty — populated via the UI/API in later phases.

## Consequences
- Re-runnable; CI seeds with `--reset` then asserts row counts (po=8, stock=10,
  disc=3, demand=15, production_jobs≥1).
- Sign-off actors arrive as display names in the mockup; the seed stores them in
  `*_by_name` columns (the `*_user_id` FKs resolve once real users exist).
