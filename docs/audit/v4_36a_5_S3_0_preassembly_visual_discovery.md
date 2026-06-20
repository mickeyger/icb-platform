# v4.36a.5 §3.0 — Pre-Assembly visual quick-win: discovery synthesis

**WO:** visual-only Pre-Assembly section above a renamed MERGE section on the Planning Board. No functional
wiring. Outcome of discovery: **clean reuse, no scope surprise — entirely frontend, no backend touch.**

## 1. Where the bay-section renders
`frontend/src/screens/Planning/BayModelLanes.tsx` (the v4.36a.1/.2/.3 surface). Layout is a
`grid grid-cols-[260px_1fr]` with **Parking** (left `<Card>`) | **Assembly** (right `<Card>`), then the
full-width **AWAITING QA** `<Card className="col-span-2">` below. The "ASSEMBLY" `<Card>` renders: a header
band (`<span>Assembly</span>` + "{n} bays · {free} free"), the bay-tiles grid
(`grid-cols-[repeat(auto-fit,minmax(132px,1fr))]`), and a footer subtitle.
**Plan:** wrap the right column in a `flex flex-col gap-4` holding a NEW **PRE-ASSEMBLY** `<Card>` (top) +
the renamed **MERGE** `<Card>` (below). Header rename is text-only; the DB ids `AssemblyBay-1..5` and the
`data-testid`/`data-bay-*` attributes are UNTOUCHED (no regression to PR #35/#36 selectors).

## 2. Bay-tile shape + Day-counter insertion point
Tiles render inline in `bays.map(...)`. Each shows a top row (`<span>{bay.code}</span>` + a state badge),
then the occupant block (`occ.vin` / `occ.customer_name`) or the empty/`pre_assembly` body. The state badge
(`rounded px-1 text-[10px] font-medium ...`) sits top-right — **the Day pill goes alongside it** (top-right
row), no prop-shape change needed: the tile already has `bay` + `occ` in scope, and `bay.since` carries the
date. PRE-ASSEMBLY tiles are a separate, self-contained render (hardcoded), so they don't touch this map.

## 3. `assembly_assigned` date — ALREADY EXPOSED (the scope question)
`BayOut.since: Optional[date]` (schemas/chassis.py:219, "assembly_assigned event_date (business date)");
`current_occupants` computes `"since": ev_date or created.date()` (chassis.py:621);
`assembly_bays_utilisation` sets `o.since = occ["since"]` (chassis.py:652). Frontend `Bay` type already has
`since?: string | null` (types.ts). **→ Day counter for MERGE jobs = `today − bay.since`, pure frontend.
NO backend change.** (§0.1/§0.14 hold.)

## 4. Engagement amber
The engagement amber is the **`status-amber`** Tailwind token (NOT a raw `amber-*` class). Used by the
Parking pool affordance + v4.36a.2 reverse-drag (`border-l-status-amber`, `bg-status-amber/10..20`,
`ring-status-amber`, `text-status-amber`) and the `awaiting_attachment` BAY_TILE
(`border-l-status-amber`). **Placeholder card:** `bg-status-amber/10` fill + `border-l-4 border-l-status-amber`
— clearly amber, visually consistent, and distinct from real cards (which use the amber LEFT BORDER on a
white fill). Matches §0.9's intent ("match the engagement amber palette"); `#FEF3C7` is the same family.

## 5. Pill language
Board pills are `rounded[-full] px-1.5/2 py-0.5 text-[10px] font-medium/bold` spans; the v4.36a.1
`awaiting_qa` pill is `bg-sky-100 text-sky-700`; state badges use `bg-<tone>/15..20 text-<tone>`; a
`StatusPill` primitive exists in `components/ui/primitives.tsx`. **Day counter** (neutral grey, §0.11):
`rounded-full bg-surface-alt px-2 py-0.5 text-[10px] font-medium text-muted`. **[DEMO] pill** (§0.9):
`rounded bg-status-amber px-1.5 py-0.5 text-[9px] font-bold uppercase text-white` — high-contrast so the
placeholder reads unmistakably as non-real.

## Flagged concerns — all resolved
- **No backend touch** — `since` is already in the API (the §0.1/§0.14 "no backend" lock holds). ✔
- **No tile prop refactor** — the Day pill reads `bay.since`/static values already in scope. ✔
- **Amber connotation** — the engagement amber is "needs-attention / not-yet-committed" (parking, reverse).
  For a DEMO placeholder that's fine (it IS a not-real attention item); the `[DEMO]` pill + footer remove any
  ambiguity. No conflict. ✔
- **Branch base** — PR #35 + #36 are MERGED to main → `feat/v4.36a.5-preassembly-visual` off **main**.

## Plan (frontend-only)
Wrap right column → add PRE-ASSEMBLY `<Card>` (subtitle §0.4; 5 tiles `Bay 1..5`; empty §0.10 for 1/3/5;
amber placeholders §0.8/§0.9 for 2/4 with `[DEMO]` pill + static Day pill + footer) → rename "Assembly"→
"MERGE" (header text only, subtitle unchanged §0.5) → add neutral Day pill (`today − bay.since`) to MERGE
occupant tiles (§0.11/§0.12, scope-limited per §0.13). `DEMO_PREASSEMBLY_CARDS` hardcoded constant (§0.14).
No ADR (visual presentation); optional ADR 0025 footnote noting the visual two-phase split precedes the
v4.36b functional split.
