"""Hedged-debt lookups for IRS Valuation col AW (swaps.debt)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import openpyxl
import pytest

from swaps.debt import (
    debt_summary_filename,
    load_debt_mtm,
    load_deal_number_map,
    resolve_hedged_debt_mtm,
)

ROOT = Path(__file__).resolve().parents[1]
DEBT = ROOT / "data" / "debt"


# ----------------------------------------------------------------- file loaders
def test_load_deal_number_map_sample():
    m = load_deal_number_map(DEBT / "Deal_Numbers.csv")
    # IRS Deal Number -> Debt Deal Number (sample file has one mapping).
    assert m["20897008"] == "19085763"


def test_load_debt_mtm_sample():
    mtm = load_debt_mtm(DEBT / debt_summary_filename(date(2026, 3, 31)))
    # Debt Deal Number -> Clean + USD Outstanding (512,134,804 + 500,000,000).
    assert mtm["19085763"] == pytest.approx(512134804.0 + 500000000.0)


def test_debt_summary_filename():
    assert debt_summary_filename(date(2026, 3, 31)) == "Deal_Summary_2026-03-31.xlsx"


def test_load_deal_number_map_missing_columns(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("foo,bar\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Debt Deal Number"):
        load_deal_number_map(p)


def test_load_debt_mtm_missing_columns(tmp_path):
    p = tmp_path / "bad.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["title"])
    ws.append(["Debt Deal Number", "NotClean"])
    ws.append([123, 1.0])
    wb.save(p)
    with pytest.raises(ValueError, match="Clean"):
        load_debt_mtm(p)


# --------------------------------------------------------------- resolution
_DEAL_MAP = {"20897008": "19085763"}
_DEBT_MTM = {"19085763": 1012134804.0}  # Clean + USD Outstanding


def test_resolve_short_uses_negated_swap_clean():
    # Short reverses the swap clean's sign.
    assert resolve_hedged_debt_mtm("T1", "Short", "", -123.45, {}, {}) == pytest.approx(123.45)
    assert resolve_hedged_debt_mtm("T1", "Short", "", 200.0, {}, {}) == pytest.approx(-200.0)


def test_resolve_short_is_case_insensitive():
    assert resolve_hedged_debt_mtm("T1", "  short ", "", 10.0, {}, {}) == pytest.approx(-10.0)


def test_resolve_long_pulls_debt_mtm():
    got = resolve_hedged_debt_mtm("T1", "Long", "20897008", 999.0, _DEAL_MAP, _DEBT_MTM)
    assert got == pytest.approx(1012134804.0)  # Clean + USD Outstanding, NOT swap clean


def test_resolve_blank_hedge_raises():
    with pytest.raises(ValueError, match="must be 'Long' or 'Short'"):
        resolve_hedged_debt_mtm("T1", "", "20897008", 1.0, _DEAL_MAP, _DEBT_MTM)


def test_resolve_unknown_hedge_raises():
    with pytest.raises(ValueError, match="must be 'Long' or 'Short'"):
        resolve_hedged_debt_mtm("T1", "Both", "20897008", 1.0, _DEAL_MAP, _DEBT_MTM)


def test_resolve_long_without_quantum_deal_raises():
    with pytest.raises(ValueError, match="requires a quantum_deal_number"):
        resolve_hedged_debt_mtm("T1", "Long", "", 1.0, _DEAL_MAP, _DEBT_MTM)


def test_resolve_long_unmapped_irs_deal_raises():
    with pytest.raises(ValueError, match="not mapped to a debt deal number"):
        resolve_hedged_debt_mtm("T1", "Long", "99999999", 1.0, _DEAL_MAP, _DEBT_MTM)


def test_resolve_long_debt_deal_missing_from_summary_raises():
    with pytest.raises(ValueError, match="not found in the Debt Summary"):
        resolve_hedged_debt_mtm("T1", "Long", "20897008", 1.0, _DEAL_MAP, {})
