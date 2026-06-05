"""Unit tests for the import_workbook ETL value helpers (WO v4.22).

Pure-function tests — no DB / no workbook I/O. Guards the parsing rules that matter:
the SA DD/MM/YYYY chassis-date parse, numeric coercion, and job-number stringify.
"""
from datetime import date, datetime


def _mod():
    # backend/ is on sys.path (conftest); `scripts` is a package under it.
    from scripts import import_workbook as m
    return m


def test_ddmmyyyy_parses_sa_dates():
    m = _mod()
    assert m._ddmmyyyy("11/02/2026") == date(2026, 2, 11)   # DD/MM/YYYY (SA)
    assert m._ddmmyyyy("19/01/2026") == date(2026, 1, 19)
    assert m._ddmmyyyy(datetime(2026, 1, 19, 8, 0)) == date(2026, 1, 19)
    assert m._ddmmyyyy("CANCELLED") is None                 # non-date text
    assert m._ddmmyyyy(None) is None
    assert m._ddmmyyyy("") is None


def test_num_coercion():
    m = _mod()
    assert m._num("7") == 7.0
    assert m._num(0.766) == 0.766
    assert m._num("") is None
    assert m._num(None) is None
    assert m._num("abc") is None


def test_job_str():
    m = _mod()
    assert m._job_str(32300) == "32300"        # int header -> no ".0"
    assert m._job_str(32300.0) == "32300"
    assert m._job_str(" 32300 ") == "32300"
    assert m._job_str("  ") is None
    assert m._job_str("#N/A") is None


def test_iso_week():
    m = _mod()
    assert m._iso_week(date(2026, 6, 1)).startswith("2026-W")
    assert m._monday(date(2026, 6, 5)) == date(2026, 6, 1)   # Friday -> Monday
