# WO v4.19 — Phase 2C-3 (Costings rewire) screenshots & live verification

Regenerate with the reusable headless step:

```bash
cd frontend
npm i -D playwright && npx playwright install chromium
node scripts/capture-v419.mjs          # MES_BASE defaults to http://localhost:8000
```

Point it at a **permitted autologin origin** serving the built SPA against a live backend
(FastAPI at `:8000` serving `/mes-app/`). The script first relies on two set-up states being
present (one fully-accepted calc + one accept-only "partial" calc — see the verification log).

## Committed PNGs
| File | Shows |
|---|---|
| `costings-dashboard-mixed-stages.png` | Live dashboard: Pending/Accepted/Pre-Job Sent/Confirmed/Planning/Repair/Rejected together, the **"Retry job creation"** partial row (Q-32898), an accepted+job row, and the bottleneck indicator. |
| `accept-success.png` | An accepted row with its production job (Q-32897). |
| `accept-partial-retry.png` | The partial row (Q-32898): **ACCEPTED + "JOB PENDING" + "Retry job creation"**. |
| `costing-detail-timeline.png` | Costing detail; live **timeline** from `/api/production-jobs/{id}/timeline`. |
| `signoff-section.png` | A Pre-Job Sent costing's dual sign-off section. |
| `planning-board-live.png` | Live board: ack candidates (pulsing Pre-Job-Confirmed cards) + schedulable pool + grid. |
| `planning-ack-from-slot.png` | **PlanningAckPanel** open from an ack candidate — writes `ackPlanning` → `/api/production-jobs/{id}/planning-ack`. |
| `branch-switch-dashboard-refetch.png` | Costings dashboard re-scoped after a branch switch. |

## Documented-not-captured (tooling limits — verified by code + live evidence below)
- **`accepted-tooltip-orderbook`** — the Flag B tooltip is a native `title` (`"Job is in the orderbook. The Pre-Job Card has not been sent to departments yet."`), confirmed live via DOM read; native title tooltips aren't OS-rendered into screenshots. The "Accepted" pill is visible in the dashboard shot.
- **`accept-flow-spinner`** — the AcceptModal shows a "Accepting…" spinner spanning both legs; it's sub-second so it isn't reliably frozen in a headless shot (verified in code + the live two-call below).
- **`chassis-received-tick`** — the live `SlotDetail` tick + the CostingDetail tick are writable (gated `production.chassis_received`); verified functionally.
- **`mock-fallback`** — backend was up for the capture; the `CostingsContext` catch → mock path is unchanged from the v4.17/v4.18 pattern.

## Live verification (admin session, `http://localhost:8000/mes-app/`)
- `npm run build` clean (tsc + vite); full backend `pytest` **green** (incl. the 2 new tests: list-item `calculation_record_id`, Flag B label guard).
- **Dual-source join (§0.1):** `/api/production-jobs` list items now carry `calculation_record_id`; the dashboard merges `/api/calculations` (spine) with the production-jobs (by calc id). Verified: 20 calcs ⋈ 15 jobs; accepted rows show the production-job `mes_status`.
- **Accept two-call (§0.2), live with CSRF:** `POST /api/calculations/4/accept → 200` then `POST /api/production-jobs/from-calculation/4 → 201` (Q-32897 → Accepted **with** a job). `POST /api/calculations/5/accept → 200` only → Q-32898 left **partial** (accepted, no job) → dashboard renders **"Retry job creation"** (the Retry re-runs step 2, idempotent).
- **CSRF:** these are the exact endpoints `CostingsContext.acceptCosting` calls; CostingsContext now rides `lib/api`, which sends `X-CSRF-Token` (the same mechanism v4.18 proved). Its raw-`fetch` mutations used to 403 silently — now fixed.
- **Flag B:** "Accepted" pill keeps its label; the orderbook tooltip is the native title above. Backend test guards the label stays `"Accepted"`.
- **Live planning-ack (§0.3):** Pre-Job-Confirmed costings appear as pulsing ack candidates on the live board; the `PlanningAckPanel` writes `ackPlanning` → `/planning-ack`. Live `SlotDetail` chassis tick is writable → `markChassisReceived` → `/chassis-received`. PlanningContext stays board-only.
- **PR formatter (§0.6):** `formatPrNumber()` renders `PR-{seq}` consistently (PO Suggestion Queue).
- No console errors throughout.
