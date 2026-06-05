# ADR 0013 — SAP-mock landing zone (`icb_sap`)

- **Status:** Accepted
- **Date:** 2026-06-05
- **Work order:** v4.23 (Phase 2D — SAP-mock schema + Inventory loader)

## Context

ICB will eventually run **SAP Business One** as the system of record for the item master and
warehouse stock. The MES needs live stock to drive the Materials/Buying/Stores surface and the
cycle-count baseline, but SAP B1 is not yet connected. Until v4.23, "SAP stock" was the 12-row
mock `icb_mes.stock_positions` table seeded from the React mockup (WO v4.15) — enough to build the
UI, but not real data and not shaped like SAP.

v4.23 lands a **mock of SAP** populated from the real **`04 - Inventory 2026.xlsx`** export
(~5 500 items, one warehouse) enriched from the **PRICE** workbook, so every Materials screen is
backed by the real item master *and* the swap to live SAP later is a connection change rather than
a re-mapping exercise.

## Decision (WO v4.23 §0, BA-locked)

### A dedicated `icb_sap` schema with SAP B1-native names
- A **third Postgres schema** `icb_sap` (alongside `icb_costings` and `icb_mes`), created by
  migration **0008** `AUTHORIZATION icb_app`. Not `*_mock` — the name reflects what it *will be*
  (the SAP landing zone), so the swap doesn't rename anything app-side.
- Tables use **SAP B1-native names**, mixed-case, quoted: **`OITM`** (item master, `ItemCode` PK),
  **`OITW`** (item-warehouse stock, composite PK `(ItemCode, WhsCode)`), **`OWHS`** (warehouses).
  Columns are SAP-native too (`OnHand`, `IsCommited` [SAP's spelling], `OnOrder`, `OnHand`, plus
  `U_`-prefixed user fields `U_ItemGroup`/`U_LastPurchasePrice`/`U_Manufacturer`). The eventual
  live source exposes these exact identifiers.
- **`OITW.Available` is a STORED generated column** (`OnHand - IsCommited + OnOrder`) and the PK is
  composite — so the schema is created by **raw DDL in migration 0008**, not model-driven
  `create_all` (generated columns + composite PKs + quoted mixed-case names don't round-trip
  cleanly). The DDL is idempotent (`IF NOT EXISTS`) so the CI upgrade→downgrade→upgrade round-trip
  stays green.
- `icb_sap` is **excluded from Alembic autogenerate** — it is not in `env.py`'s
  `_RELEVANT_SCHEMAS`, and `app.models.sap` is not imported by `env.py`. So `alembic check` ignores
  the schema and never tries to reconcile the raw-DDL tables against the ORM models. The models
  (`app/models/sap`) exist for ORM **reads** and **ETL inserts** only; `init_db()` never calls
  `create_all`, so registering them on the shared `Base` is safe.

### Read-only discipline
- **App code reads `icb_sap`, never writes it.** The only writer is the ETL loader
  `backend/scripts/import_inventory_to_sap_mock.py` (one-shot TRUNCATE+RELOAD, per Q-Ph2D-03). This
  mirrors how a real SAP integration behaves: SAP owns the data; the MES consumes it. The
  connect-listener `search_path` is **not** widened to include `icb_sap` — the ORM models are
  schema-qualified (`__table_args__={"schema": "icb_sap"}`), so they render `icb_sap."OITM"`
  explicitly regardless of `search_path`.

### Stock reads re-pointed to `icb_sap.OITW`
- `services/materials._materials_select()` now LEFT-joins `icb_sap.OITW` (by
  `mes_materials.sap_code = OITW.ItemCode`) instead of `icb_mes.stock_positions`. The
  `StockPosition` **response shape is unchanged**; only the source moves. Mapping:
  `OnHand→sap_stock`, `IsCommited→allocated`, `Available→free`, `OnOrder→open_po_qty`,
  `open_po_eta→null` (the Inventory export carries no PO ETA), `last_refreshed→OITW load time`.
- `services/stock_counts.record_count()` reads the cycle-count baseline from `OITW.OnHand` (summed
  across warehouses) for a single coherent SAP-stock source. This is the permitted "source swap",
  not new logic.
- **`free` semantics change:** it is now SAP's `Available` (= on-hand − committed + on-order), so an
  item with an incoming PO is no longer "low stock". This is more correct than the mock's old
  `free` and is reflected in the test expectations.

## Consequences

- **`icb_mes.stock_positions` is deprecated.** Nothing reads it after v4.23 (materials + stock
  counts both moved to OITW). The table and its mock seed are **retained** (not dropped) for
  rollback and to keep the seed diff small; a future WO drops it once the SAP-mock path is proven
  in UAT.
- **Single warehouse (HEIDEL) for now.** `OITW` is 1:1 per `ItemCode`, so the materials join doesn't
  fan out and `record_count` could read a single row. Both are written warehouse-robust
  (`record_count` sums; the materials join is documented as needing a per-`ItemCode` aggregation if
  a second warehouse is ever loaded).
- **CI/dev seeding:** the real Inventory workbook isn't available in CI, so `seed_from_mockup`
  mirrors the 12 mock materials into `OWHS`/`OITM`/`OITW` (guarded on schema presence). The rewired
  `/api/materials` therefore returns stock in CI exactly as before — backed by OITW instead of
  stock_positions.
- **Swap path to live SAP** (in rough order of effort): (1) a Postgres **FDW** (`postgres_fdw` /
  a SAP HANA / SQL-Server wrapper) exposing the real `OITM`/`OITW` as foreign tables under
  `icb_sap` — zero app change; (2) a **scheduled extract** replacing the one-shot loader (same
  tables, same names); (3) a **direct connection** if SAP exposes a Postgres-compatible endpoint.
  Because the names match SAP B1, none of these touch app code.

### Deferred: the `demand_lines → OITM` foreign key (build-time decision)

WO §0.5 specified adding `icb_mes.demand_lines.sap_code → icb_sap."OITM"."ItemCode"` as a
**NOT VALID** FK plus an orphan-reconciliation report. During the build this FK proved
**operationally harmful** and is **deferred** (a Q-Ph2D-05 single-blocker call), while its
**intent — measuring the demand↔item-master relationship — is delivered** via the reconciliation
report. Reasons:

1. **CASCADE nukes demand.** `demand` (workbook ETL, `icb_mes`) and `OITM` (inventory ETL,
   `icb_sap`) are loaded by **separate one-shot TRUNCATE+RELOAD ETLs**. With the FK in place,
   `TRUNCATE icb_sap."OITM" CASCADE` (the inventory reload) cascade-truncates `demand_lines` —
   observed live during the build.
2. **Blocks the independent reload cycle.** Even without CASCADE, the FK blocks truncating/reloading
   any OITM row that a demand line references, coupling two loaders that are meant to run
   independently.
3. **Breaks CI seed.** `seed_from_mockup` inserts demo `demand_lines` whose codes (e.g.
   `PNL-FLR-100-BG`) are not in the (empty-in-CI) OITM → the FK would reject the seed and red the
   pipeline.

The relationship is **real and satisfiable** — the reconciliation shows **0 of 76 distinct demand
`sap_code`s are orphans** (every demand code matches a real OITM item). So the FK is not wrong, just
premature: it should be added (and `VALIDATE`d) in a follow-on micro-WO once the two ETLs are
**coordinated** (OITM loaded before demand, or both in one transaction) and the demo seed codes are
reconciled. Flagged for BA.

## Alternatives rejected

- **`icb_sap_mock` / `mock_*` table names** — leaks "mock" into every query and the eventual swap
  becomes a rename across app + migrations. The whole point is name-parity with SAP B1.
- **Generic neutral column names** (`on_hand`, `item_code`) mapped to SAP later — defers the mapping
  cost to swap time and loses the "connection change, not re-mapping" property.
- **Putting OITM/OITW in `icb_mes`** — conflates ICB-owned production data with the SAP-owned item
  master; the read-only discipline and the future FDW swap both want a clean schema boundary.
- **Enforcing the demand→OITM FK now** (NOT VALID, as originally specified) — see the deferral
  above; it breaks the independent ETL cycles and CI for no current safety gain.
- **Computing `Available` in the app/loader** instead of a generated column — duplicates the
  formula in two places and drifts; a STORED generated column keeps it authoritative in the DB.
