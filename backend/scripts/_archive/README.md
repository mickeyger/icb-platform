# `scripts/_archive/` — retired one-shot scripts

Landing place for maintenance scripts that have served their one-shot purpose (a specific migration /
data-load / translation) and are kept only for provenance. See
[docs/scripting/archive_policy.md](../../../docs/scripting/archive_policy.md) for the policy.

Scripts here are **not** part of the supported toolset: they are not wired into CI, may reference
schemas/workbooks that no longer exist, and carry no environment-guard guarantees. Do not run them
without reading them first. This directory is intentionally empty until the first archival pass (a
deliberate, standalone change — never bundled into an unrelated WO, because moving a module changes its
import path and any references to it).
