"""Unit tests for the icb_sap (SAP-mock) loader helpers + the OITW->StockPosition
mapper (WO v4.23). Pure functions — no DB / no workbook I/O."""
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace


def _mod():
    # backend/ is on sys.path (conftest); `scripts` is a package under it.
    from scripts import import_inventory_to_sap_mock as m
    return m


def test_str_cleans_values():
    m = _mod()
    assert m._str("  GRP-MPS-A-0001 ") == "GRP-MPS-A-0001"   # trims
    assert m._str(None) is None
    assert m._str("") is None
    assert m._str("#N/A") is None                            # Excel error sentinel
    assert m._str(12345) == "12345"


def test_num_coercion():
    m = _mod()
    assert m._num("7") == 7.0
    assert m._num(0.766) == 0.766
    assert m._num("") is None
    assert m._num(None) is None
    assert m._num("abc") is None


def test_grp_cod_from_prefix():
    m = _mod()
    assert m._grp_cod("CON-FAS-A-0392") == 1     # CON
    assert m._grp_cod("GRP-MPS-A-0077") == 2     # GRP
    assert m._grp_cod("STE-PLA-A-0003") == 3     # STE
    assert m._grp_cod("ICB-XYZ-0001") == 16      # ICB
    assert m._grp_cod("con-fas-a-0001") == 1     # case-insensitive
    assert m._grp_cod("ZZZ-UNKNOWN-1") == 99     # unmapped prefix -> 99
    assert m._grp_cod("") == 99
    assert m._grp_cod(None) == 99


def test_stock_from_oitw_maps_shape():
    """OITW row -> StockPosition: OnHand->sap_stock, IsCommited->allocated,
    Available->free, OnOrder->open_po_qty; ETA null; last_refreshed = load time."""
    from app.schemas.materials import stock_from_oitw
    ts = datetime(2026, 6, 5, 9, 30, tzinfo=timezone.utc)
    # Numeric columns come back as Decimal from psycopg; the mapper must cast to float.
    w = SimpleNamespace(ItemCode="PNL-FLR-100-BG", OnHand=Decimal("4.000"),
                        IsCommited=Decimal("0.000"), OnOrder=Decimal("10.000"),
                        Available=Decimal("14.000"), updated_at=ts)
    sp = stock_from_oitw(w)
    assert sp.sap_code == "PNL-FLR-100-BG"
    assert sp.sap_stock == 4.0 and isinstance(sp.sap_stock, float)
    assert sp.allocated == 0.0
    assert sp.free == 14.0          # = Available (OnHand - IsCommited + OnOrder)
    assert sp.open_po_qty == 10.0
    assert sp.open_po_eta is None   # OITW carries no PO ETA
    assert sp.last_refreshed == ts


def test_stock_from_oitw_handles_nulls():
    from app.schemas.materials import stock_from_oitw
    w = SimpleNamespace(ItemCode="X", OnHand=None, IsCommited=None, OnOrder=None,
                        Available=None, updated_at=None)
    sp = stock_from_oitw(w)
    assert sp.sap_stock is None and sp.free is None and sp.last_refreshed is None
