"""WO v4.33 scope addition — one-shot token normalization over the prejob_templates drafts.

Replaces the Word-era placeholders with {{tokens}} (the substitution engine resolves them at
card creation; in the admin editor they stay VISIBLE — the structural-gate shape, ADR 0020
footnote 9):

  * External-dimensions lines: `0 000mm o/a (l) x 0 000mm o/a (w) x 0 000mm o/a (h)` (and the
    populated-size variants on sized templates) -> {{external_length}}/{{external_width}}/
    {{external_height}} — keyed on the o/a (l|w|h) markers, never on position.
  * `Provision for ----- fridge` dashes -> {{fridge_make}}.
  * header_format: `Chassis: -------` -> Chassis: {{chassis_make_model}};
    a trailing bare `VIN Nr:` -> VIN Nr: {{vin}}; `0 000mm` size prefix -> {{external_length}}mm.

Drafts only (is_active=False) unless --include-active. --dry-run prints the per-template
diff lines without writing.

    python -m scripts.normalize_template_tokens [--dry-run] [--include-active]
"""
from __future__ import annotations

import argparse
import re
import sys

_DIM_L = re.compile(r"\d[\d\s]*\s*mm\s+o/a\s*\(\s*l\s*\)", re.IGNORECASE)
_DIM_W = re.compile(r"\d[\d\s]*\s*mm\s+o/a\s*\(\s*w\s*\)", re.IGNORECASE)
_DIM_H = re.compile(r"\d[\d\s]*\s*mm\s+o/a\s*\(\s*h\s*\)", re.IGNORECASE)
_FRIDGE_DASHES = re.compile(r"(provision\s+for\s+)[-_]{3,}", re.IGNORECASE)
_HDR_CHASSIS = re.compile(r"(chassis:\s*)[-_]{3,}", re.IGNORECASE)
_HDR_SIZE = re.compile(r"^\s*0\s*000\s*mm")
_HDR_VIN_TRAILING = re.compile(r"(vin\s+nr:\s*)$", re.IGNORECASE)


def normalize_item_text(text: str) -> tuple[str, list[str]]:
    fixes = []
    new = _DIM_L.sub("{{external_length}}mm o/a (l)", text)
    new = _DIM_W.sub("{{external_width}}mm o/a (w)", new)
    new = _DIM_H.sub("{{external_height}}mm o/a (h)", new)
    if new != text:
        fixes.append("external dims -> tokens")
    text2 = _FRIDGE_DASHES.sub(r"\1{{fridge_make}}", new)
    if text2 != new:
        fixes.append("fridge dashes -> {{fridge_make}}")
    return text2, fixes


def normalize_header(header: str | None) -> tuple[str | None, list[str]]:
    if not header:
        return header, []
    fixes = []
    new = _HDR_CHASSIS.sub(r"\1{{chassis_make_model}}", header)
    if new != header:
        fixes.append("header chassis dashes -> token")
    new2 = _HDR_SIZE.sub("{{external_length}}mm", new)
    if new2 != new:
        fixes.append("header 0 000mm -> {{external_length}}")
    new3 = _HDR_VIN_TRAILING.sub(r"\1{{vin}}", new2.rstrip()) if new2 else new2
    if new3 != new2.rstrip():
        fixes.append("header trailing VIN -> {{vin}}")
    return new3, fixes


def run(dry_run: bool = True, include_active: bool = False) -> list[dict]:
    from app.database import SessionLocal
    from app.models.mes import PrejobTemplate
    report = []
    with SessionLocal() as db:
        q = db.query(PrejobTemplate)
        if not include_active:
            q = q.filter(PrejobTemplate.is_active.is_(False))
        for tpl in q.order_by(PrejobTemplate.name).all():
            fixes: list[str] = []
            header, hfix = normalize_header(tpl.header_format)
            fixes += hfix
            sections = tpl.sections or []
            changed_sections = []
            for section in sections:
                items = []
                for item in section.get("items", []):
                    new_text, ifix = normalize_item_text(item.get("text", ""))
                    fixes += ifix
                    items.append({**item, "text": new_text})
                changed_sections.append({**section, "items": items})
            if fixes and not dry_run:
                tpl.header_format = header
                tpl.sections = changed_sections
                tpl.version = (tpl.version or 1) + 1
                tpl.updated_by = "token-normalizer"
            if fixes:
                report.append({"template": tpl.name,
                               "fixes": sorted(set(fixes)), "count": len(fixes)})
        if not dry_run:
            db.commit()
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--include-active", action="store_true")
    args = ap.parse_args()
    if not args.dry_run:                              # --dry-run rolls back; only gate real writes.
        from scripts._environment_guard import confirm_if_shared_db
        confirm_if_shared_db("normalize_template_tokens",
                             destroys="rewrite Pre-Job template tokens in place (UPDATE rows).")
    rows = run(dry_run=args.dry_run, include_active=args.include_active)
    for r in rows:
        print(f"{r['template']:<45} {r['count']:>2} fix(es): {'; '.join(r['fixes'])}")
    print(f"\n{len(rows)} template(s) {'WOULD change' if args.dry_run else 'updated'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
