# ADR 0010 — Auth/permission model + active-branch session

- **Status:** Accepted
- **Date:** 2026-06-02
- **Work order:** v4.16 (Phase 2B-3)

## Context
v4.16 adds per-role gating to every MES mutation and a session-held "active branch".
Discovery against the costing code + dev DB found:
1. **`app/deps.py` already ships the gate.** `require_perm("key")` composes with
   `require_user`, checks `user_can()` = `role_permissions[user.role]` ∪
   `user_permissions` overrides, with **`role == "admin"` as a code-level wildcard**,
   and raises 403. It is exactly the spec's `require_permission`.
2. **The permission tables (`permissions`, `role_permissions`, `user_permissions`)
   are empty**, and `users.role` only holds `admin` / `user`. So no role resolves to
   any permission today (admin works only via the wildcard).
3. **`users` has no branch / home-branch column** — there is no per-user branch mapping.

## Decision
- **Reuse the costing auth system.** Add `require_permission = require_perm` (alias for
  the WO's naming); do **not** write a second gate. Permission strings live in
  `icb_costings.permissions`; grants in `role_permissions` (+ `user_permissions` overrides).
- **15 mutation permission keys**, `{domain}.{action}` lowercase, seeded by migration `0005`:
  - `production.accept`, `production.pre_job_card`, `production.signoff_sales`,
    `production.signoff_production`, `production.chassis_received`
  - `planning.acknowledge`, `planning.schedule`, `planning.unschedule`
  - `stores.count`, `stores.raise_discrepancy`
  - `buying.resolve_discrepancy`, `buying.raise_pr`, `buying.defer_pr`,
    `buying.override_supplier`, `buying.bulk_raise`
  - The mockup's `materials.*` carry over renamed: `materials.count → stores.count`,
    `materials.raise_pr → buying.raise_pr`, `materials.override_supplier →
    buying.override_supplier`, `materials.bulk_raise → buying.bulk_raise`. `materials.view`
    is read-side → **not gated** in v4.16.
- **Role grants** (seeded; `admin` stays code-level wildcard):

  | Role | Keys |
  |---|---|
  | `sales` | production.accept, production.pre_job_card, production.signoff_sales |
  | `production` | production.signoff_production, production.chassis_received, planning.acknowledge |
  | `planner` | planning.acknowledge, planning.schedule, planning.unschedule, production.chassis_received |
  | `stores` | stores.count, stores.raise_discrepancy |
  | `buyer` | buying.raise_pr, buying.defer_pr, buying.resolve_discrepancy |
  | `buyer_senior` | *(buyer)* + buying.override_supplier, buying.bulk_raise |

- **GET endpoints stay ungated** (read-side gating is deferred). `require_permission`
  applies to mutations only; `require_user` remains on everything.
- **Active branch is session-held.** `GET /api/session` returns the user + active branch
  + accessible branches; `POST /api/session/branch {branch_id}` switches it (validates the
  branch **exists**). Because `users` has no branch mapping, **`accessible_branches` = all
  branches** for everyone and the **default active branch = JHB**. A middleware/dependency
  (`active_branch`) resolves it; list endpoints default to it (explicit `?branch_id` overrides).

## Consequences
- One DB-backed auth system across costing + MES; no parallel MES role tables.
- Tests create one user per MES role to exercise allow/deny (403); admin is the wildcard.
- A per-user branch restriction (e.g. `users.home_branch_id`) is **not** added — deferred;
  if real per-user branch access is needed later it's an additive costing-schema change.
- ADR 0005's deferred column-drop renumbers `0005+ → 0006+` (migration `0005` is this WO).
