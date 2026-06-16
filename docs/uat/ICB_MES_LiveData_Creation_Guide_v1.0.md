# Creating real data in the MES — operator guide (post-demo) — v1.0

The v4.35 demo data is throwaway (anonymised, ~12 jobs). When you're ready to replace it with real ICB
data, build it up through the UI in the order below — each step unlocks the next. You do **not** run any
scripts for this; it's all the normal screens. (To clear the demo data first, see the bottom.)

> Master data is already real and preserved — your 2 190 customers, contacts, dealer flags, templates,
> fridge units, chassis models, users. You're only creating *workflow* data (quotes → jobs → chassis).

## The order

1. **Customer** (if new) — Admin → Customers. Most exist already; flag a chassis supplier with
   *is_dealer* if needed.
2. **Costing** — New Costing → pick the customer + body spec → save. It lands on the Costings dashboard.
3. **Accept the costing** — on the costing, Accept. This creates the production job and the Pre-Job Card
   prefilled from the costing + template.
4. **Pre-Job Card → submit for check** — fill the body gap (or waive), pick Sales Rep + Planner, submit.
   Capture the chassis VIN here when known — that VIN becomes the planner-attested spec.
5. **Both sign-offs** — Sales and Planner each sign off (Admin → Outstanding Pre-Job Sign-offs lists what's
   waiting). When both are in, the job auto-confirms and appears on the Planning Board (Unscheduled).
6. **Planning ack** — Planning Board: acknowledge the pulsing "Awaiting Ack" card; capture the chassis ETA.
   The job moves into the Unscheduled pool.
7. **Schedule** — drag the job onto a Vacuum/Press lane cell for its build week. (Need to reshuffle? drag
   it back to Unscheduled, or use "Move back to Unscheduled" on the slot — chassis + sign-offs are kept.)
8. **Chassis VCL (book-in)** — Chassis menu → the chassis → capture the VCL (book-in) event when it
   physically arrives. Status → in_workshop; the body gap flows through to the card.
9. **Assign to an assembly bay** — Planning Board bay model / Chassis: assign the booked-in chassis to a
   free assembly bay. Status → in_assembly; it now shows on the Production Dashboard bay heat-map (amber,
   "Awaiting attachment").
10. **Mark body attached** — Production Dashboard → click the bay → **Mark body attached**. The bay turns
    green, the "Bodies attached today" KPI ticks, and the Assembly tab lists it. *(Planner/production/admin;
    the workshop role is read-only for now.)*

## Caveats

- **Chassis status stays `in_assembly` after the body is attached** — by design (ADR 0025). The attach is
  surfaced on the Production Dashboard, not as a chassis-status change. (A future workshop-tablet step
  promotes it.)
- **The swap guard:** once a VIN is attested on a confirmed Pre-Job Card, the chassis you attach must match
  that VIN. If you genuinely need a different chassis, that's a planning-ack-level change.
- **Email / SAP / materials** are not live yet (intranet/Marnus-blocked) — those screens show stubs.
- **Don't run `seed_v4_35_demo_reset` against real data** — it wipes the workflow tables. It's a *demo*
  tool. Once you've built real data, retire the demo-reset from your routine.

## Clearing the demo data before you start real entry

The demo workflow data can be wiped the same way the demo is reset (a pg_dump snapshot is taken first):

```
cd backend
$env:ICB_ALLOW_SHARED_DB_WRITE = '1'
python -m scripts.seed_v4_35_demo_reset --commit     # wipes + reseeds the demo set
```

If you'd rather start from an **empty** workflow (no demo jobs at all), tell CA1 — a one-line variant of
the wipe (no reseed) can be added. For now the script always reseeds the demo set.
