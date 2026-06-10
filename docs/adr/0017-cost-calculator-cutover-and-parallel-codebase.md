# ADR 0017 — Cost Calculator unification cutover + the parallel-codebase reconciliation pattern

- **Status:** Accepted
- **Date:** 2026-06-09
- **Work order:** v4.30 (Cost Calculator Unification Cutover — retire `GRP-Costing-System`, move the live faje.co.za deploy to `icb-platform`)

## Context

The Cost Calculator existed in **two repos**: `mickeyger/GRP-Costing-System` (the live faje.co.za app) and
`mickeyger/icb-platform`, which **imported the calculator as-is at v4.12** (`d37716a`, 2026-06-02) and built
the MES on top. Every UAT release to the legacy app (the 7-Jun edit-functionality release, `d2da5bf` +
`14e6817`) widened the drift and required manual re-sync. v4.30 collapses this to **one repo, one source of
truth** by porting the outstanding drift into icb-platform and switching HostAfrica's Git-pull source.

This ADR records the **reusable pattern** for reconciling a parallel codebase and cutting over a shared deploy.

## Decision

### 1. Drift audit FIRST, by content divergence (no shared git history)

icb-platform and `GRP-Costing-System` share **no git ancestor** (the v4.12 import was a fresh repo), so a
cross-repo `git diff` from a merge-base is impossible and GitHub's compare view can't align the two trees.
The audit therefore:
- **Pins the fork instant** (icb-platform's first commits, 2026-06-02) and lists legacy commits *after* it →
  the real drift set (here: exactly the two 7-Jun commits).
- **Content-divergence-scans** every legacy `app/**.{py,js,html}` against its icb `backend/app/**` counterpart
  (`git diff --no-index --numstat`), to catch anything the dates miss and to separate genuine drift from the
  v4.12 restructuring. Each file → **PORT / KEEP-DIVERGENT / DROP**, saved to
  `docs/migrations/v4.30-drift-audit.md`, **BA-approved before any porting**. (Path map is uniform: legacy
  `app/X` → icb `backend/app/X`.)

### 2. Port faithfully, tag the legacy SHA

PORT items are applied by **3-way patch-apply of the actual legacy commits** (`git apply --3way`, after
fetching the legacy objects into the local repo), adapted to `backend/app/` paths, then committed with a
message linking the legacy SHA. This preserves the e2e-verified legacy code byte-for-byte rather than
hand-reimplementing it. Each port passes the `/calculator` byte-identical-except-intended regression check.

### 3. KEEP-DIVERGENT is a real category — and one entry is a trap

Files where **icb-platform is intentionally ahead** must NOT be overwritten by the older legacy version. The
load-bearing example:

> **`routers/pre_job_card.py` — DO NOT port from legacy.** This is the exact file the **v4.29 D2 fix** lives
> in (the planning-ack status-source deadlock, ADR 0016 §2). The legacy copy predates that fix; a careless
> "the legacy version is newer-looking" port would **silently re-introduce the D2 deadlock**. The divergence
> scan flags icb as *ahead* here; the drift register marks it KEEP-DIVERGENT with this reason.

Same logic guards `main.py`, `login.html`, `deps.py`, `auth.py`, `services.py` (→ package) — all v4.12/v4.29
evolution, not drift.

### 4. Inherited shared-DB columns ship a GUARDED Alembic migration — don't skip it

The 7-Jun release added four discount columns (`discount_kind/input/amount`, `net_total`) to
`icb_costings.calculations`. They already exist on the **shared prod DB** (faje's own deploy ran the ALTER),
so the WO's §0.2a lock said "no migration needed". That was literal-minded: icb-platform's `create_all()` and
the legacy `_run_migrations()` were **both removed at v4.12** — **Alembic is the only schema path for icb's
own CI and local DBs**, which do *not* have the columns. Skipping the migration breaks every
`CalculationRecord` query there (the ORM SELECTs columns the table lacks).

> **Pattern:** *When inheriting columns added by an external system on a shared DB, ship a **guarded**
> migration (`ADD COLUMN IF NOT EXISTS`) to keep Alembic's chain consistent — don't skip just because prod
> won't change.* On the shared prod DB it is a **strict no-op** (WO §2 "shared schema unchanged" holds); on
> icb's separately-built DBs it materialises the columns. Downgrade is a **no-op** so an accidental
> `alembic downgrade` never drops the faje-owned columns. This continues the inspector-guard idempotency
> pattern of migrations 0007 / 0009 / 0010 / 0011 / 0012 / 0014. Implemented as **migration 0015**.

### 5. The `net_total` semantic is a per-callsite decision, by view (§0.2a)

The discount means MES reads of `calculations.selling_zar` must pick a meaning per callsite:
- **Costings = a revenue view → `net_total`** (post-discount headline; `selling_zar` retained as the
  pre-discount reference, shown as "before discount" only when a discount exists).
- **Planning Board = a workload view → keep `selling_zar`** (capacity ≠ revenue; a discounted quote doesn't
  reduce production load). Both planning reads carry a `# Workload metric` comment.

Mechanism: the calculator + the `/api/calculations`/`/api/production-jobs` responses surface `net_total` (and
mirror it into `result_json`); `grand_total` becomes the net headline; `selling_zar` stays pre-discount.

### 6. Cutover = cPanel "Setup Python App" + a WSGI bridge, two-phase parallel-app

HostAfrica is cPanel + **Phusion Passenger (WSGI-only)**; FastAPI is ASGI, so the deploy needs a thin
`backend/passenger_wsgi.py` wrapping `app.main:app` via `a2wsgi.ASGIMiddleware` as the WSGI callable
`application` (mirrors the legacy). Git deploy can't target a subdirectory, but cPanel's "Setup Python App"
can point the Application **root** at `backend/` — so icb-platform stays as-is (no wrapper repo). Because
HostAfrica binds **one domain per app**, the cutover is **two-phase**: Phase 1 builds + verifies a NEW app on
a **subdomain** (zero production risk; faje.co.za untouched), Phase 2 swaps the URL (~5–10 min) with the old
app **parked ~48 h** as an instant-rollback safety net. All mechanics, the env-var contract, the
URL-editable-vs-recreate finding, and the per-phase rollback live in **`docs/runbooks/faje-deploy.md`**.
**No DB rollback** (the only schema change is additive + guarded). Post-cutover: archive `GRP-Costing-System`
(don't delete), retire the local `Costing model` folder, mark `ICB_UAT_Agent_Constraints_v1.0.md` SUPERSEDED.

### 7. Production requirements must be wheel-only on shared-hosting CageFS

HostAfrica's cPanel CageFS has **no system dev libraries** (no Cairo headers / build toolchain wired up), so a
Python dep that **compiles from source** fails `pip install` there. The staging deploy hit this on `pycairo`,
pulled transitively by `svglib==1.6.0 → rlPyCairo → pycairo` — and `svglib` turned out to be **unused by any
backend code** (no `svg2rlg`/`renderPM` import), so it was simply **removed** from `backend/requirements.txt`
(the legacy's looser `svglib>=1.5` had resolved an older, cairo-free build, which is why it never surfaced there).

> **Pattern:** *Compile-from-source Python deps fail on shared-hosting CageFS without system dev libs. Keep the
> production requirements file **wheel-only**; move any source-build or dev-only dep to a separate
> `requirements-extras.txt` the cPanel deploy doesn't install, and confirm wheels exist for the target Linux
> before pinning.* Audit **transitive** deps too — the offender here was two levels below the pinned package.

### 8. Confirm the host's DB-access + runtime constraints BEFORE the drift audit

Two staging-time surprises shared one root cause — **the target runtime's constraints weren't validated up
front**, so they surfaced at the most expensive moment (deploy), not the cheapest (planning):
- **DB engine mismatch:** the cutover assumed a "shared PostgreSQL", but the live faje app runs **MySQL** and
  icb is Postgres-only — so the cutover actually needs a Postgres DB **plus a MySQL→Postgres data migration**
  (runbook §F).
- **Egress firewall:** HostAfrica shared hosting **actively refuses outbound TCP to external DB ports**
  (confirmed: `google.com:443` works; Supabase `5432`/`6543` → connection refused / RST) as abuse-prevention.
  So an **external** managed Postgres (Supabase/Neon/RDS) is unreachable from the app. **A cPanel-LOCAL Postgres
  (host `localhost`) is NOT subject to egress filtering** — so *"does the plan offer a local PostgreSQL?"* is the
  first question to ask, ahead of any whitelist or upgrade.

> **Pattern:** *Before the drift audit (not at staging), confirm the hosting provider's: (1) supported DB
> engines + whether a **local** instance of the needed engine is offered; (2) **outbound** network policy
> (shared hosting commonly blocks egress to external DB/SMTP ports); (3) build toolchain (§7). A code-level
> cutover can be fully correct yet still blocked by a runtime/network constraint a 10-minute pre-flight
> question would have caught.* If the host can neither offer a local instance nor allow egress to a managed
> one, the decision escalates to **changing hosting** — a budget/lead-time call, not a code one.

> **Resolution (10 Jun 2026 PM):** HostAfrica shared hosting was the wrong infrastructure — PostgreSQL isn't
> offered on the shared plan, and outbound TCP to external PostgreSQL ports is actively blocked at the egress
> firewall, so neither a local nor a managed external Postgres was viable. The engagement pivoted to an **ICB
> intranet single-VM** deployment (Ubuntu 22.04 / Debian 12 — PostgreSQL 16 + uvicorn + Nginx talking over
> localhost, Nginx reverse-proxying the intranet IP, VPN access; provisioning tracked in **WO v4.35**). The
> hosting-preflight lesson stands unchanged: **validate database-engine availability + outbound network rules
> before scheduling any cutover.** The vendor questionnaire (`ICB_WebHost_Vendor_Questionnaire_v1.0.md`)
> captures the 44 questions to put to any future host before committing. The HostAfrica cutover runbook
> (`docs/runbooks/faje-deploy.md`) is retained but marked **SUPERSEDED**.

## Consequences

- **One source of truth.** No more dual-codebase coordination; UAT releases land directly in icb-platform.
- **A repeatable parallel-codebase playbook:** fork-pin → divergence-scan → categorise → 3-way port + SHA-tag
  → guarded migration for inherited shared columns → per-callsite semantics → single Git-source cutover +
  rollback runbook. Use it whenever a parallel codebase or a shared-DB drift situation recurs.
- The `pre_job_card.py` trap is the standing reminder that "newer-looking legacy file" ≠ "port it" — always
  check whether icb is *ahead*.
- A small calculator UX enhancement (new costings default the ratio to 55%; edit/copy restore their source)
  shipped alongside the port — recorded as an **intentional** deviation from "/calculator byte-identical", not
  drift.
