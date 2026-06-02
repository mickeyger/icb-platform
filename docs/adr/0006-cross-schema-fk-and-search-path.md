# ADR 0006 — Cross-schema FKs + search_path

- **Status:** Accepted
- **Date:** 2026-06-02
- **Work order:** v4.13 (Phase 2A)

## Context
`icb_mes` tables reference `icb_costings` tables (`calculations`, `branches`,
`users`). The legacy costing models are schema-less in the SQLAlchemy metadata
(they rely on the role search_path to resolve to `icb_costings`), so a
declarative `ForeignKey("icb_costings.calculations.id")` cannot resolve at
mapper-config time — and giving the whole monolith an explicit schema would
cascade-break its internal FK strings.

## Decision
- MES models declare ONLY intra-`icb_mes` FKs. Cross-schema columns
  (`calculation_record_id`, `branch_id`, every `*_user_id`) are plain `Integer`;
  their FK constraints to `icb_costings.*` are created in migration `0003` via
  `op.create_foreign_key(... referent_schema='icb_costings')`. The list lives in
  `app.models.mes.CROSS_SCHEMA_FKS`.
- `alembic/env.py` uses `include_schemas=True` + `include_name` (relevant schemas
  only) + `include_object` (exclude cross-schema FKs from autogenerate) so
  `alembic check` stays clean across both schemas.
- Every connection runs `SET search_path TO icb_mes, icb_costings, public` via a
  SQLAlchemy `connect` event listener (`app/database.py`).
- ON DELETE policy: **RESTRICT** to `calculations` / `branches` (protect
  referenced rows); **SET NULL** to `users` (preserve the audit trail when a user
  is removed).

## Consequences
- The database enforces referential integrity across schemas; `alembic check`
  reports no drift (verified) and a `DELETE` of a referenced `calculations` row
  is correctly blocked.
- Cross-schema FK changes are a migration concern, not an ORM one.
