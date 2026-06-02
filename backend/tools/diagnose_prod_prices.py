"""
Diagnose why prod prices don't match the old PRICE file cell values.

Prints the price_map (old->new), then for each prod material shows
the closest price_map key and the gap, so we can see the discrepancy.

Usage:
    DATABASE_URL="mysql+pymysql://user:pass@host/dbname" ^
        python tools/diagnose_prod_prices.py
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from tools.update_prices_from_price_list import (
    collect_price_cell_refs,
    build_cell_price_map,
    GRP_PATH, OLD_PRICE_PATH, NEW_PRICE_PATH, DATABASE_URL,
)
import sqlalchemy as sa

NEAR_THRESHOLD = 5.0  # print matches within R5

def main():
    refs      = collect_price_cell_refs(GRP_PATH)
    price_map = build_cell_price_map(refs, OLD_PRICE_PATH, NEW_PRICE_PATH)

    print("\n=== price_map (old PRICE file cell values that changed) ===")
    print(f"  {'Old value':>12}  {'New value':>12}  {'Chg':>7}")
    for old_k in sorted(price_map):
        new_k = price_map[old_k]
        pct = (new_k / old_k - 1) * 100 if old_k else 0
        print(f"  {old_k:>12.4f}  {new_k:>12.4f}  {pct:>+6.1f}%")

    engine     = sa.create_engine(DATABASE_URL,
                   connect_args={"check_same_thread": False}
                   if DATABASE_URL.startswith("sqlite") else {})
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text("SELECT id, name, price_per_unit FROM materials "
                    "WHERE is_active=1 ORDER BY price_per_unit")
        ).fetchall()

    print(f"\n=== DB materials: {len(rows)} active ===")
    print(f"  {'id':>5}  {'name':<50}  {'db_price':>10}  {'closest_old':>12}  {'gap':>8}  {'new_would_be':>12}")
    print(f"  {'-'*5}  {'-'*50}  {'-'*10}  {'-'*12}  {'-'*8}  {'-'*12}")

    matched = near = unmatched = 0
    for mid, mname, mprice in rows:
        if mprice is None:
            continue
        # Find closest price_map key
        closest_key = min(price_map.keys(), key=lambda k: abs(mprice - k))
        gap = abs(mprice - closest_key)

        if gap <= 0.01:
            matched += 1
            tag = "<-- MATCH"
        elif gap <= NEAR_THRESHOLD:
            near += 1
            tag = f"<-- near (gap={gap:.4f})"
        else:
            unmatched += 1
            tag = ""

        if gap <= NEAR_THRESHOLD:
            new_would = price_map[closest_key]
            print(f"  {mid:>5}  {mname:<50}  {mprice:>10.4f}  {closest_key:>12.4f}  {gap:>8.4f}  {new_would:>12.4f}  {tag}")

    print(f"\nSummary: {matched} matched (gap<=0.01), {near} near (0.01<gap<=5), {unmatched} unmatched")

if __name__ == "__main__":
    main()
