# v4.38 Feedback Portal — §3.0 Discovery & Reuse Map

> **Status:** Discovery complete. BA-confirmed direction (4× GO, 2026-06-23). **NO feature code,
> NO alembic applied yet** — Week-1 build is gated on BA sign-off of the refined sprint below.
> This is the formal §3.0 artifact (supersedes the scratch `v4_38_S0_handoff.md`).
>
> **Author:** CA4 (Feedback Portal). **Base:** `feat/v4.38-feedback-portal` @ `97d5c56` (= `origin/main`).
> **Companions:** [`../handoffs/CA3_GRP_AI_Port_Inventory.md`](../handoffs/CA3_GRP_AI_Port_Inventory.md) (reference map).

---

## 0. Headline

The kickoff's core premise — *port the Claude/Haiku AI layer cross-repo from `GRP-Costing-System`* —
is **superseded by native infrastructure already in icb-platform**. The repo ships a complete,
production-grade, Haiku-powered assistant under `backend/app/help/` + `backend/app/routers/help.py`.
**v4.38 mirrors the in-repo `app/help/` patterns** (same SDK, same conventions, same repo) instead of
porting from GRP. CA3's inventory becomes a *reference* (which guardrails to keep, the new-table-on-prod
caveat), not the port source. Net effect: the backend AI cost is near-zero and **simpler** than the
help feature, because v4.38 needs neither the 8 data-lookup tools nor the action/nav allowlist.

---

## 1. Workspace & branch provenance

| Item | Value |
|---|---|
| Worktree | `C:/Users/micge/Documents/icb-platform-v4.38` (git worktree; object store shared with primary clone) |
| Branch | `feat/v4.38-feedback-portal`, off `origin/main` @ `97d5c56` ("Fix main CI … #45") |
| Remote | `origin = https://github.com/mickeyger/icb-platform.git` ✓ |
| Primary clone | `C:/Users/micge/Documents/icb-platform` stays on CA1's `feat/v4.36b-chassis-fields-unification` with uncommitted WIP — **untouched** |
| Dev server port | **8001** (CA1 owns 8000) |

**Non-negotiable constraints carried in (kickoff §D):** `/calculator` (Jinja) byte-identical · `icb_sap.*`
READ-ONLY (ADR 0013) · `ICB_ALLOW_SHARED_DB_WRITE=0` in prod · v4.34.4 invariants held · no v4.31–v4.36a.5
surface regression · widget renders on `/mes-app/*` React routes ONLY · no prod deploy without BA.

---

## 2. Integration points (verified at main HEAD in this worktree)

| Concern | Finding | Evidence |
|---|---|---|
| **Backend AI** | Native `AsyncAnthropic` assistant, SSE, tool-use loop, rate-limit, telemetry. **Already on Haiku.** | `routers/help.py`; `help/__init__.py:41` default `claude-haiku-4-5-20251001` |
| **SDK present** | `anthropic==0.104.1` already a dependency | `backend/requirements.txt:52` |
| **API-key gate** | `is_configured()` = `bool(ANTHROPIC_API_KEY)`; absent ⇒ 503 + button hidden | `help/__init__.py:48`; `help.py:455-459` |
| **Streaming gotcha** | SSE is **buffered in memory then returned as one `Response`** — the `BaseHTTPMiddleware` stack breaks true mid-stream SSE on prod. **Reuse this shape.** | `help.py:517-537` |
| **Router registration** | Clean `include_router` list; `_r_help` already wired | `main.py:155-203` (esp. `:173`) |
| **SPA / Jinja split** | React mounted under `/mes-app/` only; `/calculator`, `/`, `/api/*`, `/static` are separate Jinja routes | `main.py:408-429` |
| **Widget mount** | `Layout.tsx` wraps every route in `App.tsx` → a `<FeedbackWidget/>` there shows on every MES screen and **cannot** touch `/calculator` (byte-identical satisfied by construction) | `components/layout/Layout.tsx`; `App.tsx` |
| **Admin inbox** | `screens/Admin/AdminModule.tsx` + `/admin/:resource` route exist; `/mes-app/admin/feedback` is the pre-spec'd route | `App.tsx:55`; CA3 inv. A.6.1 |
| **Existing widget UX** | Floating launcher + panel, fetch+ReadableStream SSE parse, localStorage history — vanilla JS to adapt → React/TS | `static/js/help_chat.js` |
| **Email (server send)** | **No server-side SMTP sender exists** (`0` `smtplib`/`SMTP(`/`sendmail` hits in `backend/app`). Pre-Job "email" is a `build_email()` payload + `mailto:` link. `SMTP_URL` config declared but unused (empty = dev). | `services/prejob_cards.py:526`; `config.py:48` |
| **WhatsApp/Twilio** | **None** — greenfield notifications layer | grep `twilio\|whatsapp` = 0 |
| **html2canvas** | Not in `package.json` — new frontend dep; **risk:** canvas-rendered Planning Board capture (validate Week 1) | grep = 0 |

---

## 3. Reuse map — mirror / port-guardrail / build-new

### 3a. MIRROR from `app/help/` (structure, into a new `app/feedback/`)

| Source | What to mirror | v4.38 adaptation |
|---|---|---|
| `help/__init__.py` | `get_model()` (Haiku default + `ANTHROPIC_HELP_MODEL`-style override), `is_configured()` | Direct; own model-env name e.g. `ANTHROPIC_FEEDBACK_MODEL` (default Haiku) |
| `help/prompts.py` `build_system_blocks()` | `cache_control:ephemeral` persona block | New v4.38 PERSONA (classify + clarify, **not** costing Q&A) |
| `help/prompts.py` `build_user_turn()` / `truncate_history()` | Per-turn message assembly + history cap | Context shape = the submission (`page_url`, `user_text`, screenshot meta) |
| `routers/help.py` rate-limit + `_persist_log()` + SSE-buffered-`Response` | 30/hr sliding window; telemetry; the buffered-SSE shape | Keep rate-limit; classification likely **one structured call** (non-streaming); clarifying-loop can stream |

### 3b. PORT FAITHFULLY (guardrails — CA3 A.5 + `prompts.py` rules)

1. **No code/implementation disclosure** (`prompts.py:29-36`) — the classifier sees bug text; its user-visible reply must not leak schema/files/routes.
2. **Read-only / permission-respecting** — classification never writes business data.
3. **Rate limit** 30/hr/user (mirror `help.py:39-55`).
4. **API-key absent ⇒ graceful 503 + hidden affordance** (no crash).

### 3c. BUILD NEW (v4.38-specific)

- `app/feedback/prompts.py` — classification PERSONA (→ `issue_type ∈ {bug,question,feature,data}`, `severity ∈ {blocker,major,minor,nice}`, `probable_cause`, `clarifying_questions[1..3]`) + clarifying-loop PERSONA. **Structured output** (tool/JSON-schema-forced), unlike help's free-text stream.
- `app/routers/feedback.py` — `POST /api/feedback` (submit→classify), `POST /api/feedback/{id}/answer` (clarifying), `GET /api/admin/feedback`, `GET|PATCH /api/admin/feedback/{id}`.
- `services/notifications.py` — one interface: **email send** (new server-side SMTP sender consuming `SMTP_URL`; no-op when empty, mirroring the existing dev-mode contract) + **Twilio WhatsApp** (abstraction + log-stub until creds land).
- **alembic migration** — `feedback_submissions` (+ screenshot blob path). **Create the table EXPLICITLY** in the migration — per CA3 A.4, `Base.metadata.create_all` does not reliably create new tables on a prod restart.
- Frontend — `FeedbackWidget.tsx` (adapt `help_chat.js`) in `Layout.tsx`; `screens/Admin/FeedbackInbox.tsx` at `/admin/feedback`; html2canvas capture.

### 3d. EXPLICITLY NOT NEEDED (simplification vs the help feature)

- The **8 data-lookup tools** (`help/tools.py:194-353`) — classification doesn't query business data.
- The **`propose_actions` action/nav allowlist** — CA3 A.6.1: "v4.38 classifies issues; it does **not** navigate users → the navigate allowlist barely matters for CA4." Drop it.
- `reconcile.py` / `autofix.py` / Excel-audit — that's v4.37 scope, not v4.38.

---

## 4. ⚠ Migration coordination (cross-CA)

- **Alembic head on `origin/main` = `0025_chassis_soft_delete`.** CA1's unmerged v4.36b adds `0026_chassis_tail_lift_code`.
- My `feedback_submissions` migration must chain off the **real** main head at creation time. If I author against 0025 and v4.36b lands first, I **rebase the `down_revision`** onto 0026 to avoid an alembic multi-head. **Do NOT blindly claim 0026/0027** — confirm with `alembic heads` at author time.
- **Per worktree guidance: surface migration timing to BA before applying.** Cleanest order: let v4.36b (0026) land on main, then author mine as the next single head.

## 5. Frontend merge coordination (cross-CA)

- v4.36b edits `App.tsx` + `TopNav.tsx`; v4.38 inserts `<FeedbackWidget/>` into `Layout.tsx` (and registers the `/admin/feedback` screen in `App.tsx`). Overlap is small. Design the mount as a **single near-conflict-free insertion**; rebase on main after v4.36b lands (planned first).

---

## 6. Decisions resolved (BA, 2026-06-23) & open asks

**Resolved (4× GO):** (1) **Isolated git worktree** off main. (2) **Mirror in-repo `app/help/`**; CA3 inventory = reference only. (3) **Twilio** for WhatsApp (sandbox for dev; prod Sender verification in parallel). (4) **Proceed on kickoff + this discovery**; BA writes the formal WO in parallel to reconcile §0 locks against observed reality.

**Open asks to BA (not blocking the artifact; blocking specific deliverables):**
- **Migration timing** — confirm whether to author after v4.36b's 0026 lands (preferred) or author-now-and-rebase.
- **Twilio creds** — `TWILIO_ACCOUNT_SID/AUTH_TOKEN/WHATSAPP_FROM/WHATSAPP_TO` in `/etc/icb/backend.env` (gates the live WhatsApp send in Week 2; abstraction+stub proceeds without).
- **`ANTHROPIC_API_KEY`** — confirm present in the dev/prod env the portal runs against (already gates the existing help feature).
- Defaults adopted unless redirected: table in `icb_mes`; any logged-in user submits, admin-only inbox; **one Haiku call per submission** (cost discipline, §H).

---

## 7. Refined sprint structure (2 weeks; backend AI cost ≈ 0)

**Week 1 — endpoint + widget + delivery MVP**
- §3.0 artifact (this file) committed · `app/feedback/` (mirror `app/help/`) · `routers/feedback.py` `POST /api/feedback` · structured classification call · `feedback_submissions` migration (explicit `create_table`, down_revision coordinated) · `FeedbackWidget.tsx` in `Layout.tsx` + html2canvas · **new server-side email sender** (`SMTP_URL`) · admin inbox skeleton · 1 journey test.

**Week 2 — AI depth + WhatsApp + dashboard + hardening**
- Classification + clarifying-questions loop (v4.38 prompts) · Twilio WhatsApp (sandbox) · admin dashboard lifecycle (submitted→triaged→in-progress→resolved→closed) · 3-subagent adversarial review (security / stress / silent-deferral sweep) · journey test · **verify-cycle close on `icb`** (snapshot→mutate→verify→reseed→confirm) · deploy via BA (Option B).

---

## 8. §3.0 verification checklist (click-to-verify)

- Worktree — `git -C C:/Users/micge/Documents/icb-platform-v4.38 status` → branch `feat/v4.38-feedback-portal`, remote `mickeyger/icb-platform.git`
- Native AI — open `backend/app/routers/help.py` + `backend/app/help/__init__.py` → `AsyncAnthropic`, default `claude-haiku-4-5-20251001`
- No server SMTP — `rg "smtplib|SMTP\(|sendmail" backend/app` → **0 hits**
- No Twilio — `rg -i "twilio|whatsapp" .` → **0 hits**
- Alembic head — `ls backend/alembic/versions | grep ^00 | sort | tail -1` → `0025_chassis_soft_delete` (NOT 0026 on this base)
- SPA split — `backend/app/main.py:408-429` → `/mes-app` mount distinct from `/calculator`

*Generated 2026-06-23 for the v4.38 §3.0 checkpoint. Reconcile against `ICB_MES_WorkOrder_v4.38_FeedbackPortal_FORMAL.md` §0 locks when the BA files it.*
