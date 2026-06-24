# v4.38 Feedback Portal — Week-0 Setup & Handoff

> **Status:** pre-discovery. NO code, NO commits, NO alembic yet (per kickoff: wait for BA
> sign-off on §3.0 discovery + sprint structure). This note bridges a session relaunch —
> it is an uncommitted scratch record, not the formal §3.0 artifact.

## Workspace provenance
- **This is a git worktree.** Path: `C:/Users/micge/Documents/icb-platform-v4.38`.
- Branch: `feat/v4.38-feedback-portal`, created off `origin/main` @ `97d5c56`
  ("Fix main CI… (#45)"). Upstream intentionally **unset** (no accidental push-to-main).
- The primary clone `C:/Users/micge/Documents/icb-platform` stays on CA1's branch
  `feat/v4.36b-chassis-fields-unification` with uncommitted WIP — **do not touch it.**
- `legacy_costing` remote on icb-platform points at the local GRP-Costing-System path —
  GRP is READ-ONLY reference for the Claude/Haiku port; never commit to GRP.

## Outstanding asks to BA (Michael) — needed before any CODE is written
1. **WO file `ICB_MES_WorkOrder_v4.38_FeedbackPortal_FORMAL.md` does not exist** anywhere
   in the Documents tree. It carries the binding §0 locks. Need it before build.
2. **CA3's `CA3_GRP_AI_Port_Inventory.md` does not exist.** Mitigant found: icb-platform
   ALREADY has an Anthropic-powered module to reuse (see preliminary findings) — so the
   port reference may matter less than the kickoff assumed, but still confirm.
3. The 7 memory files the kickoff names (`project_icecold_bodies` + six `feedback_*`
   discipline files) do not exist in the memory store. Operating off the real memory set
   instead (verify-before-prod-claims, ask-before-pushing-prod, warn-before-diverting,
   no-native-dialogs, help-no-code-disclosure, track-backend-changes, prod-new-tables-manual).

## Preliminary §3.0 findings (cross-checked vs CA1's checkout — RE-VERIFY vs origin/main base)
- **Alembic head on origin/main = `0025_chassis_soft_delete`.** CA1's unmerged v4.36b adds
  `0026_chassis_tail_lift_code`. ⚠ Coordinate my migration number/`down_revision` to avoid
  a multi-head collision at merge. Do NOT blindly take 0026.
- **No Twilio / WhatsApp anywhere** in icb-platform → notifications layer is greenfield.
- **Anthropic SDK already integrated**: `backend/app/routers/help.py` + `backend/app/help/`
  (prompts.py, tools.py, reconcile.py, redact.py, autofix.py). This is the in-repo reuse
  template for `services/feedback_ai.py` — likely cleaner than porting from GRP.
- **Widget mount point overlap with CA1:** `frontend/src/App.tsx` and
  `frontend/src/components/layout/TopNav.tsx` are edited by v4.36b. Both v4.36b and v4.38
  will touch them → merge conflict expected. Design the global `<FeedbackWidget/>` mount as
  a minimal, near-conflict-free insertion; BA to sequence (ideally v4.36b lands first).
- Constraint reminder: `/calculator` (Jinja) byte-identical; `icb_sap.*` READ-ONLY;
  `ICB_ALLOW_SHARED_DB_WRITE=0`; widget renders on `/mes-app/*` React routes ONLY.

## Next steps for the relaunched CA4 session
1. Re-run §3.0 mini-discovery (read-only) against THIS worktree base (origin/main), not
   CA1's checkout — confirm the preliminary findings above.
2. Land the synthesis as the formal artifact `docs/audit/v4_38_S3_0_week1_discovery.md`.
3. Surface kickoff items #1–#4 (read-confirmation, discovery, sprint structure, concerns)
   and WAIT for BA go before touching code / running alembic.
