"""WO v4.33 §3.2 — template importer parse/normalize tests on 5 pre-converted fixtures.

CI never runs Word COM (the .doc conversion is a dev-box concern): these fixtures are the
representative .docx set covering every §0.15 normalization branch — heading canonicalisation
("GRP SECTION:" + "SUBFRAME SECTION:" variants), the "Body gab" typo fix, the Nadie-Q5
content-keyed Icecream item drop (Mid/Big yes, 2.3m untouched), the table-layout template
(Explosive — sub_items + note attachment), CHASSIS MODIFICATIONS for the trailer body-only
class, and product_line derivation incl. the v1.1-Finding-3 content upgrade. Pure parsing —
no DB writes.
"""
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "prejob_templates"


def _parse(name: str):
    from scripts.import_prejob_templates import normalize, parse_docx
    return normalize(parse_docx(FIXTURES / name))


def _section(t, name):
    return next(s for s in t.sections if s["name"] == name)


def test_icecream_small_normalizes_headings_and_typo():
    t = _parse("Job Template (2.3m Icecream Body).docx")
    assert t.body_type == "icecream" and t.size_category == "2.3m"
    assert t.product_line == "standard"
    assert [s["name"] for s in t.sections] == [
        "GRP SECTION", "SUB FRAME SECTION", "FINISHING SECTION"]
    sub = _section(t, "SUB FRAME SECTION")
    gap_items = [i for i in sub["items"] if "Body gap" in i["text"]]
    assert gap_items, "Body gab -> Body gap fix must land in SUB FRAME"
    assert not any("body gab" in i["text"].lower()
                   for s in t.sections for i in s["items"])
    # 2.3m is NOT one of the Q5 copy-paste templates — no drop fix logged.
    assert not any("misplaced" in f for f in t.fixes)


def test_icecream_big_drops_misplaced_grp_item():
    t = _parse("Job Template (Big Icecream Body).docx")
    assert t.size_category == "big"
    grp = _section(t, "GRP SECTION")
    assert not any("3cr12" in i["text"].lower() for i in grp["items"]), \
        "the misplaced doorframe line must be dropped from GRP (Nadie Q5)"
    assert any("misplaced" in f for f in t.fixes)


def test_trailer_body_only_sections_and_product_line_upgrade():
    t = _parse("Job Template (15.5m Rhinorange Body Only).docx")
    assert t.body_type == "trailer" and t.size_category == "15.5m"
    names = [s["name"] for s in t.sections]
    assert "CHASSIS MODIFICATIONS" in names and "SUB FRAME SECTION" not in names
    # filename says bare "Rhinorange" but the document header says 2.0 (v1.1 Finding 3)
    assert t.product_line == "rhinorange_2_0"


def test_rhinorange_legacy_stays_legacy():
    t = _parse("Job Templates (Big Rhinorange Meathanger Body).docx")
    assert t.body_type == "meathanger" and t.product_line == "rhinorange_legacy"


def test_explosive_table_layout_subitems_and_note():
    """The Explosive template is a 2-column number|text TABLE (doc.paragraphs sees only the
    header) — the table walker must recover all three sections, the HazChem sub-list
    (v1.3 Finding 14) and the solid-panel note (Finding 16)."""
    t = _parse("Job Template (Explosive Body).docx")
    assert t.body_type == "explosive"
    assert [s["name"] for s in t.sections] == [
        "GRP SECTION", "SUB FRAME SECTION", "FINISHING SECTION"]
    fin = _section(t, "FINISHING SECTION")
    hazchem = [i for i in fin["items"] if i.get("sub_items")]
    assert hazchem and len(hazchem[0]["sub_items"]) == 10
    assert hazchem[0]["sub_items"][0].startswith("(Below 3.5ton)")
    grp = _section(t, "GRP SECTION")
    assert any(i.get("note") == "Rear will be solid panel." for i in grp["items"])
    # the table's numbering column must not leak "1"/"2" items
    assert not any(i["text"].isdigit() for s in t.sections for i in s["items"])


def test_derive_metadata_variants():
    from scripts.import_prejob_templates import derive_metadata
    m = derive_metadata("Job Template (15.5m Rhinorange 2.0 Tri Axle Trailer).docx", None)
    assert m == {"name": "15.5m Rhinorange 2.0 Tri Axle Trailer", "body_type": "trailer",
                 "size_category": "15.5m", "product_line": "rhinorange_2_0"}
    m = derive_metadata("Job Templete (Middle Freezer Body).docx", None)   # filename typo tolerated
    assert m["body_type"] == "freezer" and m["size_category"] == "mid"
    assert m["product_line"] == "standard"
    m = derive_metadata("Job Template (Dry Freight Body).docx", None)
    assert m["body_type"] == "dry_freight" and m["size_category"] is None
