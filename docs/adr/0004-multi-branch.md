# ADR 0004 — Single tenant, multi-branch

- **Status:** Accepted
- **Date:** 2026-06-02
- **Work order:** v4.12 (Phase 1)

## Context
Icecold is a single company operating multiple branches (Johannesburg, Cape
Town, Central). Operational records (costings, customers, snapshots) need to be
attributable to a branch. Phase 1 is a **data foundation only** — no UI.

## Decision
Add a `branches` table (`icb_costings.branches`, seeded **JHB / CPT / CEN**) and
a **nullable** `branch_id` foreign key on the operational tables — `customers`,
`calculations`, `bom_snapshots`, `configurator_snapshots`,
`configurator_drafts` — backfilled to the default branch (JHB). Reference/global
data (materials, formulas, permissions, commodity quotes) is not branch-scoped.

This is multi-**branch**, NOT multi-**tenant**: there is no `tenant_id` and no
row-level security. Cloud multi-tenancy was answered "no for now" (Unified
Codebase Plan §10, Q-UC-02).

## Consequences
- The schema is ready for branch-aware queries; the branch UI arrives in Phase 2.
- `branch_id` is nullable, so existing flows are unaffected; the default branch
  is configurable via `DEFAULT_BRANCH_CODE`.
- Should a second tenant ever emerge, a separate `tenant_id` design is required;
  this ADR explicitly scopes that out.
