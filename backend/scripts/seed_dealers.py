"""WO v4.34.1 §3.7 — seed dealers as a flag on the existing customers table.

Reads dealers.txt (one "Dealer - End Customer" line each), extracts the DEALER PREFIX (the part
before ' - '; the suffix is the end customer the chassis was for, not the dealer), de-duplicates
(so 'ITC Midrand - Cultiver/Eggspert Eggs/Petit Forestier' collapse to one 'ITC Midrand', and the
two 'Ronnies Motors' lines collapse to one), then 4-step fuzzy-matches each unique dealer against
icb_costings.customers:

  1. exact       — case-insensitive whole-name equality
  2. normalised  — equal after lower-casing + stripping all non-alphanumerics
  3. prefix      — one normalised name is a prefix of the other (min 5 chars; catches
                   'ITC Midrand' ⊂ 'ITC Midrand (Pty) Ltd')
  4. inserted    — no customer matched → INSERT a new is_dealer customer

Matched customers are flagged is_dealer=true (an entity can be both a biller and a chassis supplier).
Writes a CSV decision log (one row per unique dealer: match type + customer + the source lines that
collapsed into it) and prints a summary. Idempotent + forward-only: re-running only sets flags /
inserts the still-missing, never un-flags.

Usage:
    python -m scripts.seed_dealers [--file dealers.txt] [--out dealer_seed_decisions.csv] [--dry-run]
"""
import argparse
import csv
import re
import sys
from collections import OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select                                # noqa: E402

from app.database import Customer, SessionLocal             # noqa: E402

_HERE = Path(__file__).resolve().parent


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _dealer_prefix(line: str) -> str:
    """The dealer name = the part before ' - ' (the suffix is the end customer)."""
    return line.split(" - ", 1)[0].strip()


def load_unique_dealers(path: Path) -> "OrderedDict[str, list[str]]":
    """Return {canonical_dealer_name: [source lines]} preserving first-seen order + display casing."""
    out: "OrderedDict[str, dict]" = OrderedDict()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        dealer = _dealer_prefix(line)
        if not dealer:
            continue
        key = _norm(dealer)
        if key not in out:
            out[key] = {"display": dealer, "lines": []}
        out[key]["lines"].append(line)
    return OrderedDict((v["display"], v["lines"]) for v in out.values())


def seed(file_path: Path, out_path: Path, dry_run: bool = False) -> dict:
    dealers = load_unique_dealers(file_path)
    db = SessionLocal()
    decisions = []
    stats = {"unique": len(dealers), "exact": 0, "normalised": 0, "prefix": 0, "inserted": 0, "flagged": 0}
    try:
        customers = db.execute(select(Customer.id, Customer.name)).all()
        by_lower = {(name or "").strip().lower(): cid for cid, name in customers}
        by_norm = {}
        for cid, name in customers:
            by_norm.setdefault(_norm(name), cid)
        norm_list = [(_norm(name), cid, name) for cid, name in customers]

        def flag(cid: int):
            c = db.get(Customer, cid)
            if c is not None and not c.is_dealer:
                c.is_dealer = True
                stats["flagged"] += 1

        for dealer, src_lines in dealers.items():
            ndealer = _norm(dealer)
            match_type = match_id = match_name = None
            if dealer.strip().lower() in by_lower:                          # 1. exact
                match_type, match_id = "exact", by_lower[dealer.strip().lower()]
            elif ndealer in by_norm:                                        # 2. normalised
                match_type, match_id = "normalised", by_norm[ndealer]
            else:                                                           # 3. prefix (min 5 chars)
                for ncust, cid, name in norm_list:
                    if len(ndealer) >= 5 and len(ncust) >= 5 and (ncust.startswith(ndealer) or ndealer.startswith(ncust)):
                        match_type, match_id, match_name = "prefix", cid, name
                        break
            if match_type is None:                                          # 4. inserted
                new = Customer(name=dealer, is_dealer=True, is_active=True)
                db.add(new)
                db.flush()
                match_type, match_id = "inserted", new.id
                stats["inserted"] += 1
            else:
                flag(match_id)
                stats[match_type] += 1
                if match_name is None:
                    match_name = db.get(Customer, match_id).name
            decisions.append({"dealer": dealer, "match_type": match_type, "customer_id": match_id,
                              "customer_name": match_name or dealer, "source_lines": " | ".join(src_lines)})

        if dry_run:
            db.rollback()
        else:
            db.commit()
    finally:
        db.close()

    with out_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["dealer", "match_type", "customer_id", "customer_name", "source_lines"])
        w.writeheader()
        w.writerows(decisions)
    return {"stats": stats, "decisions": decisions, "out": out_path}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", default=str(_HERE / "dealers.txt"))
    ap.add_argument("--out", default=str(_HERE / "dealer_seed_decisions.csv"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    from scripts._environment_guard import announce_target   # additive: insert/flag dealers, never deletes
    announce_target("seed_dealers")
    r = seed(Path(args.file), Path(args.out), dry_run=args.dry_run)
    s = r["stats"]
    print(f"[seed_dealers] {'DRY-RUN — ' if args.dry_run else ''}28 lines -> {s['unique']} unique dealers")
    print(f"  exact={s['exact']}  normalised={s['normalised']}  prefix={s['prefix']}  inserted={s['inserted']}")
    print(f"  customers newly flagged is_dealer={s['flagged']}  (+{s['inserted']} inserted)")
    print(f"  decision log -> {r['out']}")


if __name__ == "__main__":
    main()
