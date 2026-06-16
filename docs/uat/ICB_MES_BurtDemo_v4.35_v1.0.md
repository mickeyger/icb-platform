# Burt Demo Runbook — v4.35 (Body↔Chassis Attached) — v1.0

A step-by-step walkthrough for the 22-23 June owner demo. The story: a costing becomes a job, the job is
planned, the chassis arrives and goes to an assembly bay, **the body is joined to the chassis**, and the
floor sees it happen. Screenshots are from the live demo data; your screen will match after the
pre-demo reset below.

---

## ⛔ DO NOT SKIP — run this once, Monday AM, before you open the laptop for Burt

The demo data is throwaway and you may have clicked around it. Restore the canonical state:

```
cd backend
$env:ICB_ALLOW_SHARED_DB_WRITE = '1'          # PowerShell (deliberate friction — see ADR 0023)
python -m scripts.seed_v4_35_demo_reset --commit
python -m scripts.health_check                 # expect: CLEAN — all three invariants hold
```

This wipes the workflow data and reseeds the canonical demo (12 jobs, all bay states), preserving all
master data (customers, templates, users). It takes a few seconds. The script is idempotent — safe to
re-run. (A pre-wipe pg_dump snapshot already exists; the script is also atomic + invariant-gated.)

Then start the app the usual way and open **Production**.

---

## The walkthrough

### 1 · Production Dashboard — the floor at a glance
Open **Production**. The top strip leads with the keystone metric — **Bodies attached today** — beside
the live floor KPIs. Below it, the five assembly bays show their state at a glance.

![Production dashboard](../screenshots/runbook/01-production-kpi-and-bays.png)

**Talk track:** "This is the workshop floor. Two bodies have been joined to their chassis today. Each bay
tile shows what's in it and where it is in the join: amber = chassis waiting for its body, green = body
attached today, blue = finishing."

*If Burt asks "what's a bay state?"* — point at the colours: **AssemblyBay-2/-3 (amber, Awaiting)**,
**-4/-5 (green, Attached today)**, **-1 (Finishing)**.

### 2 · The bay detail + the join moment
Click **AssemblyBay-2** (amber). The side panel shows the **lifecycle checklist** — Chassis received ✓,
Assigned to assembly bay ✓, Body attached ○ — and the **Mark body attached** action.

![Bay side panel](../screenshots/runbook/03-sidepanel-mark-attached.png)

**Talk track:** "The chassis is in the bay; the body isn't on yet. When the team joins them, we record it
right here." Type an optional note, click **🔗 Mark body attached**.

![After attach](../screenshots/runbook/04-after-attach-bay-flipped.png)

The bay turns green ("Attached today"), the **Bodies attached today** KPI ticks up, and a confirmation
shows. *That's the keystone — the moment the MES represents the factory joining the body to the chassis.*

### 3 · Where it shows up — Assembly tab
In the **Team daily worksheet**, open the **Assembly** tab. A **"Body Attached (today)"** section lists
the jobs joined today.

![Assembly section](../screenshots/runbook/05-assembly-body-attached-section.png)

### 4 · Tracing it back — Vacuum/Press + Planning
The panel side of the floor knows the chassis too. The **Vacuum** tab shows each slot's chassis **VIN**
under the job number; the **Planning Board** shows the same on its scheduled cells — so a planner can
match VIN-to-VIN without a lookup.

![Vacuum slot VINs](../screenshots/runbook/06-vacuum-slot-vin.png)
![Planning slot VINs](../screenshots/runbook/07-planning-slot-vin.png)

### 5 · Roles — the floor is read-only for the workshop
Signed in as a workshop user, the bay panel shows the state but **no Mark-body-attached button** — the
floor *sees* the workflow; recording it is the planner/production role (the tablet write-path is a future
step).

![Workshop read-only](../screenshots/runbook/08-workshop-readonly.png)

---

## Notes for the presenter

- **"The chassis page still says 'in_assembly' after I attached the body — is that a bug?"** No — by
  design (ADR 0025): the chassis page is the chassis *lifecycle audit*; the *workflow moment* lives on the
  Production Dashboard (bay tile + Assembly section + KPI). A future enhancement (workshop tablet, v4.36+)
  promotes the attach to a chassis-status milestone.
- **Bay vocabulary is 4 states** for this demo: Available · Awaiting attachment · Attached today ·
  Finishing. (Two extra states — "Pre-assembly" and "Ready to merge" — arrive with the Planning
  panel-drag enhancement; if that ships, this runbook gains them.)
- **If Burt asks about email / SAP / materials** — those are blocked on the intranet/Marnus work and out
  of scope for this demo; the flow shown is the production workflow as designed.
- **If a bay won't mark attached** — it's guarded: the job must be in production, the chassis must be on
  the bay, and if a VIN was attested at planning-ack the chassis must match. The error toast says which.

## Reset between dry-runs
If you mark a body attached during a dry-run and want the two amber bays back, just re-run the
**DO NOT SKIP** reset above. It restores the canonical state every time.
