"""Hedged-debt valuation + IRS col AW resolution (swaps.debt)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from swaps.debt import (
    DEBT_SUMMARY_FIELDS,
    debt_summary_filename,
    debt_summary_row,
    resolve_hedged_debt_mtm,
    value_debt,
    write_debt_summary_csv,
)
from swaps.loaders.base import TradeDef
from swaps.loaders.excel import ExcelCurveLoader
from swaps.trade_builder import build_debt_leg

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def _bond_trade(**overrides) -> TradeDef:
    """An LH trade carrying the real deal-19085763 bond (5.625% 2034 AXP note)."""
    kw = dict(
        trade_id="IRS_HEDGE_001",
        notional=500_000_000, pay_fixed=True, fixed_rate=0.05,
        start_date=date(2024, 1, 1), maturity_date=date(2034, 7, 28),
        fixed_frequency="6M", fixed_daycount="30/360",
        floating_spread=0.0,
        oracle_entity_code="1000", notional_currency="USD",
        hedge="LH",
        debt_deal_number="19085763",
        debt_fixed_rate=0.05625, debt_notional=500_000_000,
        debt_settlement_date=date(2023, 7, 28),
        debt_frequency="6M", debt_daycount="30/360",
        debt_counterparty="Barclays Bank - US", debt_cusip="025816DK2",
        debt_gaap_category="1 Year & 90 Day Callable LT Debt",
        debt_instrument="Unsecured Fixed", debt_rate_type="FIXED",
    )
    kw.update(overrides)
    return TradeDef(**kw)


# ----------------------------------------------------------------- filename
def test_debt_summary_filename():
    assert debt_summary_filename(date(2026, 3, 31)) == "Debt_Summary_2026-03-31.csv"


# --------------------------------------------------------------- valuation
def test_value_debt_structural():
    ff = ExcelCurveLoader(DATA / "curves").load(date(2026, 3, 31), "FEDFUNDS")
    v = value_debt(_bond_trade(), ff, date(2026, 3, 31))
    # Signed from the obligor's view -> Clean/Accrued/Dirty are negative
    # liabilities. Dirty = Clean + Accrued exactly; premium-bond magnitude.
    assert v["dirty"] == pytest.approx(v["clean"] + v["accrued"])
    assert v["accrued"] < 0
    assert -1.2 * 500_000_000 < v["clean"] < -0.9 * 500_000_000


def test_value_debt_reconciles_with_legacy_sheet():
    # Legacy externally-produced numbers (different curve/model): Clean
    # 512,134,804 / Accrued 4,921,875. Our Fed-Funds-discounted model should land
    # in the same neighbourhood ("better numbers", not an exact match).
    ff = ExcelCurveLoader(DATA / "curves").load(date(2026, 3, 31), "FEDFUNDS")
    v = value_debt(_bond_trade(), ff, date(2026, 3, 31))
    # Accrued is curve-independent -> reproduces the legacy 30/360 magnitude
    # exactly, negated to the obligor's sign.
    assert v["accrued"] == pytest.approx(-4_921_875.0, rel=1e-6)
    # Clean is curve-driven; ours discounts on Fed Funds, theirs on a different
    # curve, so expect "same neighbourhood" (~15%), not an exact match.
    assert v["clean"] == pytest.approx(-512_134_804.0, rel=0.15)


def test_build_debt_leg_requires_settlement_date():
    with pytest.raises(ValueError, match="debt_settlement_date"):
        build_debt_leg(_bond_trade(debt_settlement_date=None))


def test_build_debt_leg_settlement_after_maturity_raises():
    with pytest.raises(ValueError, match="before maturity_date"):
        build_debt_leg(_bond_trade(debt_settlement_date=date(2035, 1, 1)))


# --------------------------------------------------------------- resolution
_LH_VALUE = 512134804.0 + 500000000.0  # Clean + USD Outstanding


def test_resolve_sc_uses_negated_swap_clean():
    assert resolve_hedged_debt_mtm("T1", "SC", "", -123.45) == pytest.approx(123.45)
    assert resolve_hedged_debt_mtm("T1", "SC", "", 200.0) == pytest.approx(-200.0)


def test_resolve_sc_is_case_insensitive():
    assert resolve_hedged_debt_mtm("T1", "  sc ", "", 10.0) == pytest.approx(-10.0)


def test_resolve_lh_returns_precomputed_value():
    got = resolve_hedged_debt_mtm("T1", "LH", "19085763", 999.0, _LH_VALUE)
    assert got == pytest.approx(1012134804.0)  # Clean + Outstanding, NOT swap clean


def test_resolve_blank_hedge_raises():
    with pytest.raises(ValueError, match="must be 'LH' or 'SC'"):
        resolve_hedged_debt_mtm("T1", "", "19085763", 1.0, _LH_VALUE)


def test_resolve_unknown_hedge_raises():
    with pytest.raises(ValueError, match="must be 'LH' or 'SC'"):
        resolve_hedged_debt_mtm("T1", "Long", "19085763", 1.0, _LH_VALUE)


def test_resolve_lh_without_debt_deal_raises():
    with pytest.raises(ValueError, match="requires a debt_deal_number"):
        resolve_hedged_debt_mtm("T1", "LH", "", 1.0, _LH_VALUE)


def test_resolve_lh_debt_not_valued_raises():
    with pytest.raises(ValueError, match="could not be valued"):
        resolve_hedged_debt_mtm("T1", "LH", "99999999", 1.0, None)


# ------------------------------------------------------------- summary csv
def test_write_debt_summary_csv_roundtrip(tmp_path):
    rows = [debt_summary_row(_bond_trade(), clean=512_000_000.0, accrued=4_900_000.0,
                             dirty=516_900_000.0)]
    p = write_debt_summary_csv(tmp_path / "Debt_Summary.csv", rows)
    lines = p.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("Hedged Debt details")
    assert lines[1].split(",") == DEBT_SUMMARY_FIELDS
    # Debt Deal Number cell present; Fixed Coupon rendered in percent.
    assert "19085763" in lines[2]
    assert "5.625" in lines[2]
