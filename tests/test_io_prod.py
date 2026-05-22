"""Prod CSV writer (KPMG IRS valuation feed)."""

from __future__ import annotations

import csv
from datetime import date

import pandas as pd
import pytest

from swaps.io_prod import (
    CME_NAME, N_COLS, PROD_FIELDS, SOURCE_NAME, VERSION_STAMP,
    _COL, _SUM_COLS, load_entity_rc, prod_filename, write_prod_csv,
)
from swaps.loaders.base import TradeDef
from swaps.pricer import SwapValuation


VAL = date(2026, 5, 20)


def _valuation(trade_id="T1", clean=1000.0, accrued=50.0, dirty=1050.0, dv01=2.5,
               pv_fixed=100000.0, pv_floating=101050.0) -> SwapValuation:
    return SwapValuation(
        trade_id=trade_id, val_date=VAL,
        clean=clean, accrued=accrued, dirty=dirty, dv01=dv01,
        pv_fixed=pv_fixed, pv_floating=pv_floating,
        par_rate=0.0431, rate_diff_bp=2.5,
        fixed_cf=pd.DataFrame(), floating_cf=pd.DataFrame(),
        floating_cf_by_period=pd.DataFrame(),
        meta={},
    )


def _trade(trade_id="T1", current_counterparty="JP Morgan Chase Bank NA",
           intercompany=False, **overrides) -> TradeDef:
    kw = dict(
        trade_id=trade_id, notional=500_000_000.0, pay_fixed=False, fixed_rate=0.0541,
        start_date=date(2026, 3, 9), maturity_date=date(2031, 3, 9),
        fixed_frequency="1M", fixed_daycount="ACT/360",
        quantum_deal_number="QD-1", oracle_entity_code="ORC-1",
        notional_currency="USD", intercompany=intercompany,
        counterparty_name_quantum="JPM", current_counterparty=current_counterparty,
        entity_name_quantum="AMEX_NA_001", reporting_party="Amex NA",
        counterparty_location="US", deal_date=date(2026, 3, 5),
        netting_id="NID-1", cash_flow_netting_allowed="Yes",
        position_netting_allowed="Yes",
    )
    kw.update(overrides)
    return TradeDef(**kw)


def _read(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return list(csv.reader(fh))


# --- structure ---------------------------------------------------------------
def test_layout_header_field_row_trade_row_footer(tmp_path):
    td = _trade()
    v = _valuation()
    p = write_prod_csv(tmp_path / "out.csv", {td.trade_id: td}, [v], VAL)
    rows = _read(p)
    # 1 header + 1 field-name row + 1 trade row + 1 footer
    assert len(rows) == 4
    # row 1: 5-cell header
    assert rows[0] == ["H", "20260520", prod_filename(VAL), VERSION_STAMP, SOURCE_NAME]
    # row 2: 49 field headers in the spec order
    assert rows[1] == PROD_FIELDS
    assert len(rows[1]) == N_COLS == 49
    # trade + footer rows have 49 cells
    assert len(rows[2]) == N_COLS
    assert len(rows[3]) == N_COLS
    # footer starts with T and trade count
    assert rows[3][0] == "T"
    assert rows[3][1] == "1"


def test_filename_format():
    assert prod_filename(VAL) == "IRS Valuation2026-05-20-00001.csv"


# --- field mapping -----------------------------------------------------------
def test_constants_filled_correctly(tmp_path):
    td = _trade()
    v = _valuation()
    p = write_prod_csv(tmp_path / "out.csv", {td.trade_id: td}, [v], VAL)
    row = _read(p)[2]
    assert row[_COL["Valuation Currency"]] == "USD"
    assert row[_COL["Product"]] == "IR"
    assert row[_COL["HCL Type"]] == "Interest Rate Swap"
    assert row[_COL["Collateral Level"]] == "Fully Collateralized"
    assert row[_COL["As of Date"]] == VAL.isoformat()


def test_pricing_fields_threaded_through(tmp_path):
    td = _trade()
    v = _valuation(clean=1234.5, accrued=67.8, dirty=1302.3, dv01=9.1, pv_fixed=222.0)
    p = write_prod_csv(tmp_path / "out.csv", {td.trade_id: td}, [v], VAL)
    row = _read(p)[2]
    assert float(row[_COL["Clean price"]]) == pytest.approx(1234.5)
    assert float(row[_COL["Accrued Interest"]]) == pytest.approx(67.8)
    assert float(row[_COL["Total Value (NPV)"]]) == pytest.approx(1302.3)
    assert float(row[_COL["DV01"]]) == pytest.approx(9.1)
    assert float(row[_COL["Hedged Debt MTM"]]) == pytest.approx(222.0)


def test_notional_q_equals_r(tmp_path):
    td = _trade(notional=750_000_000.0)
    v = _valuation()
    p = write_prod_csv(tmp_path / "out.csv", {td.trade_id: td}, [v], VAL)
    row = _read(p)[2]
    assert float(row[_COL["Notional 1 Amount"]]) == 750_000_000.0
    assert float(row[_COL["Notional 1 Amount USD"]]) == 750_000_000.0


def test_intercompany_bool_renders_yes_no(tmp_path):
    td_yes = _trade(intercompany=True)
    td_no = _trade(intercompany=False)
    v = _valuation()
    p1 = write_prod_csv(tmp_path / "yes.csv", {td_yes.trade_id: td_yes}, [v], VAL)
    p2 = write_prod_csv(tmp_path / "no.csv", {td_no.trade_id: td_no}, [v], VAL)
    assert _read(p1)[2][_COL["Intercompany Trade"]] == "Yes"
    assert _read(p2)[2][_COL["Intercompany Trade"]] == "No"


# --- CME branch (exact string match) -----------------------------------------
def test_cme_exact_match_routes_to_centralized(tmp_path):
    td = _trade(current_counterparty=CME_NAME)
    v = _valuation()
    p = write_prod_csv(tmp_path / "out.csv", {td.trade_id: td}, [v], VAL)
    row = _read(p)[2]
    assert row[_COL["Sub-Product2"]] == "OTC - Centralized (Principal)"
    assert row[_COL["Counterparty Type"]] == "Financial Market Utility"
    assert row[_COL["Qualifying Central Counterparty Indicator"]] == "Yes"
    assert row[_COL["Cleared Transaction indicator"]] == "Yes"
    assert row[_COL["Cash Settled CCP indicator"]] == "Yes"


@pytest.mark.parametrize("name", [
    "cme clearing house",            # case
    " CME Clearing House",            # leading whitespace
    "CME Clearing House ",            # trailing whitespace
    "CME",                            # short form
    "CME Clearing",                   # partial
    "",                               # blank
])
def test_non_exact_cme_routes_to_bilateral(tmp_path, name):
    td = _trade(current_counterparty=name)
    v = _valuation()
    p = write_prod_csv(tmp_path / "out.csv", {td.trade_id: td}, [v], VAL)
    row = _read(p)[2]
    assert row[_COL["Sub-Product2"]] == "OTC - Bilateral"
    assert row[_COL["Counterparty Type"]] == "Bank"
    assert row[_COL["Qualifying Central Counterparty Indicator"]] == "No"


# --- DA / DL / Asset Liability tag ------------------------------------------
def test_positive_npv_fills_da(tmp_path):
    td = _trade()
    v = _valuation(dirty=500.0)
    p = write_prod_csv(tmp_path / "out.csv", {td.trade_id: td}, [v], VAL)
    row = _read(p)[2]
    assert float(row[_COL["DA"]]) == 500.0
    assert row[_COL["DL"]] == ""
    assert row[_COL["Asset Liability Tag"]] == "Asset"


def test_negative_npv_fills_dl(tmp_path):
    td = _trade()
    v = _valuation(dirty=-300.0)
    p = write_prod_csv(tmp_path / "out.csv", {td.trade_id: td}, [v], VAL)
    row = _read(p)[2]
    assert row[_COL["DA"]] == ""
    assert float(row[_COL["DL"]]) == -300.0
    assert row[_COL["Asset Liability Tag"]] == "Liability"


def test_zero_npv_leaves_da_dl_tag_blank(tmp_path):
    td = _trade()
    v = _valuation(dirty=0.0)
    p = write_prod_csv(tmp_path / "out.csv", {td.trade_id: td}, [v], VAL)
    row = _read(p)[2]
    assert row[_COL["DA"]] == "" and row[_COL["DL"]] == ""
    assert row[_COL["Asset Liability Tag"]] == ""


# --- Footer sums -------------------------------------------------------------
def test_footer_sums_match_column_letter_spec(tmp_path):
    td1 = _trade("T1", current_counterparty="X")
    td2 = _trade("T2", current_counterparty="X")
    v1 = _valuation("T1", clean=100.0, accrued=10.0, dirty=110.0, dv01=1.0, pv_fixed=1.0)
    v2 = _valuation("T2", clean=200.0, accrued=20.0, dirty=-50.0, dv01=2.0, pv_fixed=2.0)
    p = write_prod_csv(tmp_path / "out.csv", {"T1": td1, "T2": td2}, [v1, v2], VAL)
    rows = _read(p)
    footer = rows[-1]
    assert footer[0] == "T"
    assert footer[1] == "2"
    assert float(footer[_COL["Clean price"]]) == pytest.approx(300.0)
    assert float(footer[_COL["Accrued Interest"]]) == pytest.approx(30.0)
    assert float(footer[_COL["Total Value (NPV)"]]) == pytest.approx(60.0)
    assert float(footer[_COL["DV01"]]) == pytest.approx(3.0)
    assert float(footer[_COL["Notional 1 Amount"]]) == pytest.approx(1_000_000_000.0)
    assert float(footer[_COL["Notional 1 Amount USD"]]) == pytest.approx(1_000_000_000.0)
    assert float(footer[_COL["DA"]]) == pytest.approx(110.0)        # only v1 positive
    assert float(footer[_COL["DL"]]) == pytest.approx(-50.0)         # only v2 negative
    assert float(footer[_COL["Hedged Debt MTM"]]) == pytest.approx(3.0)
    # The three FV-columns are always blank; their sums must be 0.
    for fv in ("Coupon FV (Future Value)", "Intrinsic Value FV (Future Value)",
               "Time Value FV (Future Value)"):
        assert float(footer[_COL[fv]]) == 0.0


def test_empty_portfolio_produces_header_field_footer_only(tmp_path):
    p = write_prod_csv(tmp_path / "out.csv", {}, [], VAL)
    rows = _read(p)
    assert len(rows) == 3
    assert rows[0][0] == "H"
    assert rows[1] == PROD_FIELDS
    assert rows[2][0] == "T" and rows[2][1] == "0"


# --- CCID (cols AU / AV) -----------------------------------------------------
_ENTITY_RC = {"1000": "100008", "1001": "100058"}


def test_ccid_asset_uses_192001(tmp_path):
    td = _trade(oracle_entity_code="1000")
    v = _valuation(dirty=1000.0)  # NPV > 0 -> Asset
    p = write_prod_csv(tmp_path / "out.csv", {td.trade_id: td}, [v], VAL,
                       entity_rc=_ENTITY_RC)
    row = _read(p)[2]
    assert row[_COL["Balance Sheet CCID"]] == \
        "1000-100008-192001-000000-0000-000000-000000-000000-0000"
    assert row[_COL["PL/OCI CCID"]] == \
        "1000-100008-465012-000000-0000-000000-000000-000000-0000"


def test_ccid_liability_uses_392001(tmp_path):
    td = _trade(oracle_entity_code="1000")
    v = _valuation(dirty=-1000.0)  # NPV < 0 -> Liability
    p = write_prod_csv(tmp_path / "out.csv", {td.trade_id: td}, [v], VAL,
                       entity_rc=_ENTITY_RC)
    row = _read(p)[2]
    assert row[_COL["Balance Sheet CCID"]] == \
        "1000-100008-392001-000000-0000-000000-000000-000000-0000"
    assert row[_COL["PL/OCI CCID"]] == \
        "1000-100008-465012-000000-0000-000000-000000-000000-0000"


def test_ccid_zero_npv_blanks_bs_but_fills_pl(tmp_path):
    td = _trade(oracle_entity_code="1001")
    v = _valuation(clean=0.0, accrued=0.0, dirty=0.0)
    p = write_prod_csv(tmp_path / "out.csv", {td.trade_id: td}, [v], VAL,
                       entity_rc=_ENTITY_RC)
    row = _read(p)[2]
    assert row[_COL["Balance Sheet CCID"]] == ""
    assert row[_COL["PL/OCI CCID"]] == \
        "1001-100058-465012-000000-0000-000000-000000-000000-0000"


def test_ccid_missing_entity_or_lookup_leaves_blanks(tmp_path):
    # entity blank -> blanks
    td_blank = _trade(oracle_entity_code="")
    v = _valuation(dirty=1000.0)
    p = write_prod_csv(tmp_path / "blank.csv", {td_blank.trade_id: td_blank}, [v], VAL,
                       entity_rc=_ENTITY_RC)
    row = _read(p)[2]
    assert row[_COL["Balance Sheet CCID"]] == ""
    assert row[_COL["PL/OCI CCID"]] == ""

    # entity present but missing from lookup -> blanks
    td_miss = _trade(oracle_entity_code="9999")
    p = write_prod_csv(tmp_path / "miss.csv", {td_miss.trade_id: td_miss}, [v], VAL,
                       entity_rc=_ENTITY_RC)
    row = _read(p)[2]
    assert row[_COL["Balance Sheet CCID"]] == ""
    assert row[_COL["PL/OCI CCID"]] == ""

    # entity_rc itself None (default) -> blanks
    p = write_prod_csv(tmp_path / "none.csv", {td_miss.trade_id: td_miss}, [v], VAL)
    row = _read(p)[2]
    assert row[_COL["Balance Sheet CCID"]] == ""
    assert row[_COL["PL/OCI CCID"]] == ""


def test_load_entity_rc_reads_sample_report(tmp_path):
    src = tmp_path / "Entity_Reference_Report.csv"
    src.write_text(
        "Entity_Code,Default RC\n1000,100008\n1001,100058\n",
        encoding="utf-8",
    )
    assert load_entity_rc(src) == {"1000": "100008", "1001": "100058"}


def test_load_entity_rc_missing_file_returns_empty(tmp_path):
    assert load_entity_rc(tmp_path / "does_not_exist.csv") == {}


# --- Sum-cols coverage sanity (lets the spec drift catch itself) ------------
def test_sum_cols_match_spec_columns():
    expected_letters = {"G", "H", "I", "J", "Q", "R", "U", "V", "W", "AK", "AL", "AW"}
    # 0-based -> spreadsheet column letter
    def to_letter(i):
        i += 1
        s = ""
        while i:
            i, r = divmod(i - 1, 26)
            s = chr(65 + r) + s
        return s
    assert {to_letter(i) for i in _SUM_COLS} == expected_letters
