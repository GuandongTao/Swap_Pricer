"""IRS Netting CSV writer (KPMG Position Netting feed)."""

from __future__ import annotations

import csv
from datetime import date

import pandas as pd
import pytest

from swaps.io_prod import CME_NAME
from swaps.io_prod_netting import (
    NETTING_FIELDS, N_NETTING_COLS, _NCOL, netting_filename, write_netting_csv,
)
from swaps.loaders.base import TradeDef
from swaps.netting_db import NettingRow
from swaps.pricer import SwapValuation


VAL = date(2026, 5, 20)
RC = {"1000": "100008", "1021": "200021"}


def _v(trade_id, dirty):
    return SwapValuation(
        trade_id=trade_id, val_date=VAL,
        clean=dirty - 5.0, accrued=5.0, dirty=dirty, dv01=1.0,
        pv_fixed=0.0, pv_floating=0.0,
        par_rate=0.05, rate_diff_bp=0.0,
        fixed_cf=pd.DataFrame(), floating_cf=pd.DataFrame(),
        floating_cf_by_period=pd.DataFrame(),
        meta={},
    )


def _t(trade_id, nid, current_counterparty="JP Morgan Chase Bank NA"):
    return TradeDef(
        trade_id=trade_id, notional=1_000_000.0, pay_fixed=False, fixed_rate=0.05,
        start_date=date(2026, 1, 1), maturity_date=date(2031, 1, 1),
        fixed_frequency="1Y", fixed_daycount="ACT/360",
        netting_id=nid, oracle_entity_code="1000",
        current_counterparty=current_counterparty,
    )


def _nrow(nid, cf="Yes", pn="Yes", entity="1000",
          legal="American Express Parent", external="JP Morgan Chase Bank NA"):
    return NettingRow(
        netting_id=nid, cash_flow_netting_allowed=cf, position_netting_allowed=pn,
        netting_entity=entity, amex_legal_entity_name=legal, external_name=external,
    )


def _read(p):
    with open(p, "r", encoding="utf-8", newline="") as fh:
        return list(csv.reader(fh))


def test_filename_format():
    assert netting_filename(VAL) == "IRS_Netting_2026-05-20-00001.csv"


def test_header_field_row_and_footer(tmp_path):
    tds = {"T1": _t("T1", "NID-1")}
    vs = [_v("T1", 100.0)]
    db = {"NID-1": _nrow("NID-1")}
    p = write_netting_csv(tmp_path / "n.csv", tds, vs, VAL, db, RC)
    rows = _read(p)
    # header + field row + 1 group row + footer
    assert len(rows) == 4
    assert rows[0][0] == "H"
    assert rows[0][2] == netting_filename(VAL)
    assert rows[0][3] == "00001"
    assert rows[0][4] == "KPMG"
    assert rows[1] == NETTING_FIELDS
    assert len(rows[1]) == N_NETTING_COLS == 21
    assert rows[-1][0] == "T"
    assert rows[-1][1] == "1"   # 1 trade in the group


def test_aggregation_math_two_sided(tmp_path):
    # Two trades same netting_id: +300 and -180 -> Gross DA 300, DL 180,
    # Netting 180, Net DA 120, Net DL 0.
    tds = {"T1": _t("T1", "NID-1"), "T2": _t("T2", "NID-1")}
    vs = [_v("T1", 300.0), _v("T2", -180.0)]
    db = {"NID-1": _nrow("NID-1")}
    p = write_netting_csv(tmp_path / "n.csv", tds, vs, VAL, db, RC)
    row = _read(p)[2]
    assert float(row[_NCOL["Gross DA"]]) == pytest.approx(300.0)
    assert float(row[_NCOL["Gross DL"]]) == pytest.approx(180.0)
    assert float(row[_NCOL["Netting Amount"]]) == pytest.approx(180.0)
    assert float(row[_NCOL["Net DA"]]) == pytest.approx(120.0)
    assert float(row[_NCOL["Net DL"]]) == pytest.approx(0.0)


def test_aggregation_one_sided_da_only(tmp_path):
    tds = {"T1": _t("T1", "NID-1"), "T2": _t("T2", "NID-1")}
    vs = [_v("T1", 200.0), _v("T2", 50.0)]
    db = {"NID-1": _nrow("NID-1")}
    p = write_netting_csv(tmp_path / "n.csv", tds, vs, VAL, db, RC)
    row = _read(p)[2]
    assert float(row[_NCOL["Gross DA"]]) == pytest.approx(250.0)
    assert float(row[_NCOL["Gross DL"]]) == 0.0
    assert float(row[_NCOL["Netting Amount"]]) == 0.0
    assert float(row[_NCOL["Net DA"]]) == pytest.approx(250.0)
    assert float(row[_NCOL["Net DL"]]) == 0.0


def test_position_netting_not_allowed_forces_zero_netting(tmp_path):
    # Same two-sided book as test_aggregation_math_two_sided, but Position
    # Netting Allowed = "N" -> Netting Amount forced to 0, so Net DA/DL = Gross.
    tds = {"T1": _t("T1", "NID-1"), "T2": _t("T2", "NID-1")}
    vs = [_v("T1", 300.0), _v("T2", -180.0)]
    db = {"NID-1": _nrow("NID-1", pn="N")}
    p = write_netting_csv(tmp_path / "n.csv", tds, vs, VAL, db, RC)
    row = _read(p)[2]
    assert float(row[_NCOL["Gross DA"]]) == pytest.approx(300.0)
    assert float(row[_NCOL["Gross DL"]]) == pytest.approx(180.0)
    assert float(row[_NCOL["Netting Amount"]]) == 0.0
    assert float(row[_NCOL["Net DA"]]) == pytest.approx(300.0)
    assert float(row[_NCOL["Net DL"]]) == pytest.approx(180.0)


def test_position_netting_allowed_y_still_nets(tmp_path):
    # Sanity: "Y" (production encoding) keeps the standard min() offset.
    tds = {"T1": _t("T1", "NID-1"), "T2": _t("T2", "NID-1")}
    vs = [_v("T1", 300.0), _v("T2", -180.0)]
    db = {"NID-1": _nrow("NID-1", pn="Y")}
    p = write_netting_csv(tmp_path / "n.csv", tds, vs, VAL, db, RC)
    row = _read(p)[2]
    assert float(row[_NCOL["Netting Amount"]]) == pytest.approx(180.0)
    assert float(row[_NCOL["Net DA"]]) == pytest.approx(120.0)
    assert float(row[_NCOL["Net DL"]]) == pytest.approx(0.0)


def test_groups_sorted_by_netting_id(tmp_path):
    tds = {
        "TA": _t("TA", "NID-B"),
        "TB": _t("TB", "NID-A"),
    }
    vs = [_v("TA", 100.0), _v("TB", 50.0)]
    db = {
        "NID-A": _nrow("NID-A", external="ANZ Bank"),
        "NID-B": _nrow("NID-B", external="Bank of America"),
    }
    p = write_netting_csv(tmp_path / "n.csv", tds, vs, VAL, db, RC)
    rows = _read(p)
    assert rows[2][_NCOL["Netting ID"]] == "NID-A"
    assert rows[3][_NCOL["Netting ID"]] == "NID-B"


def test_ccids_use_netting_entity_and_192005_392004(tmp_path):
    tds = {"T1": _t("T1", "NID-1")}
    vs = [_v("T1", 100.0)]
    db = {"NID-1": _nrow("NID-1", entity="1021")}
    p = write_netting_csv(tmp_path / "n.csv", tds, vs, VAL, db, RC)
    row = _read(p)[2]
    assert row[_NCOL["Position Netting Asset CCID"]] == \
        "1021-200021-192005-000000-0000-000000-000000-000000-0000"
    assert row[_NCOL["Position Netting Liability CCID"]] == \
        "1021-200021-392004-000000-0000-000000-000000-000000-0000"


def test_cme_routes_counterparty_type_to_fmu(tmp_path):
    # CME branch keys off the trade-level current_counterparty (NOT the DB).
    tds = {"T1": _t("T1", "NID-1", current_counterparty=CME_NAME)}
    vs = [_v("T1", 100.0)]
    db = {"NID-1": _nrow("NID-1")}
    p = write_netting_csv(tmp_path / "n.csv", tds, vs, VAL, db, RC)
    row = _read(p)[2]
    assert row[_NCOL["Counterparty"]] == CME_NAME
    assert row[_NCOL["Counterparty Type"]] == "Financial Market Utility"


def test_non_cme_routes_to_bank(tmp_path):
    tds = {"T1": _t("T1", "NID-1", current_counterparty="JP Morgan Chase Bank NA")}
    vs = [_v("T1", 100.0)]
    db = {"NID-1": _nrow("NID-1")}
    p = write_netting_csv(tmp_path / "n.csv", tds, vs, VAL, db, RC)
    row = _read(p)[2]
    assert row[_NCOL["Counterparty"]] == "JP Morgan Chase Bank NA"
    assert row[_NCOL["Counterparty Type"]] == "Bank"


def test_entity_is_always_american_express_company(tmp_path):
    tds = {"T1": _t("T1", "NID-1")}
    vs = [_v("T1", 100.0)]
    # DB's amex_legal_entity_name is intentionally something different to
    # show it's ignored.
    db = {"NID-1": _nrow("NID-1", legal="Some other legal name from DB")}
    p = write_netting_csv(tmp_path / "n.csv", tds, vs, VAL, db, RC)
    assert _read(p)[2][_NCOL["Entity"]] == "American Express Company"


def test_counterparty_taken_from_first_trade_in_group(tmp_path):
    # Two trades same netting_id; both should carry the same cpty in
    # practice. We take the first one to stay deterministic.
    tds = {
        "T1": _t("T1", "NID-1", current_counterparty="Bank of America"),
        "T2": _t("T2", "NID-1", current_counterparty="Bank of America"),
    }
    vs = [_v("T1", 100.0), _v("T2", -50.0)]
    db = {"NID-1": _nrow("NID-1")}
    p = write_netting_csv(tmp_path / "n.csv", tds, vs, VAL, db, RC)
    assert _read(p)[2][_NCOL["Counterparty"]] == "Bank of America"


def test_blank_netting_id_trades_skipped(tmp_path):
    # Trade with blank netting_id is not on the netting feed at all.
    tds = {"T1": _t("T1", ""), "T2": _t("T2", "NID-1")}
    vs = [_v("T1", 999.0), _v("T2", 100.0)]
    db = {"NID-1": _nrow("NID-1")}
    p = write_netting_csv(tmp_path / "n.csv", tds, vs, VAL, db, RC)
    rows = _read(p)
    # Only NID-1 -> 1 group row + header + field row + footer
    assert len(rows) == 4
    assert rows[2][_NCOL["Netting ID"]] == "NID-1"
    assert rows[-1][1] == "1"  # footer trade count counts only NID-1


def test_missing_netting_id_in_db_raises(tmp_path):
    tds = {"T1": _t("T1", "NID-MISSING")}
    vs = [_v("T1", 100.0)]
    with pytest.raises(ValueError, match="not found in netting database"):
        write_netting_csv(tmp_path / "n.csv", tds, vs, VAL,
                          {"NID-1": _nrow("NID-1")}, RC)


def test_blank_netting_entity_raises(tmp_path):
    tds = {"T1": _t("T1", "NID-1")}
    vs = [_v("T1", 100.0)]
    db = {"NID-1": _nrow("NID-1", entity="")}
    with pytest.raises(ValueError, match="blank 'Netting Entity'"):
        write_netting_csv(tmp_path / "n.csv", tds, vs, VAL, db, RC)


def test_missing_rc_for_netting_entity_raises(tmp_path):
    tds = {"T1": _t("T1", "NID-1")}
    vs = [_v("T1", 100.0)]
    db = {"NID-1": _nrow("NID-1", entity="9999")}
    with pytest.raises(ValueError, match="no RC found for netting entity"):
        write_netting_csv(tmp_path / "n.csv", tds, vs, VAL, db, RC)


def test_footer_sums(tmp_path):
    tds = {
        "T1": _t("T1", "NID-A"),
        "T2": _t("T2", "NID-A"),
        "T3": _t("T3", "NID-B"),
    }
    vs = [_v("T1", 300.0), _v("T2", -200.0), _v("T3", 100.0)]
    db = {
        "NID-A": _nrow("NID-A"),
        "NID-B": _nrow("NID-B"),
    }
    p = write_netting_csv(tmp_path / "n.csv", tds, vs, VAL, db, RC)
    rows = _read(p)
    footer = rows[-1]
    assert footer[0] == "T"
    assert footer[1] == "3"   # 3 trades total
    # Group A: GA=300 GL=200 N=200 NetDA=100 NetDL=0
    # Group B: GA=100 GL=0   N=0   NetDA=100 NetDL=0
    assert float(footer[_NCOL["Gross DA"]]) == pytest.approx(400.0)
    assert float(footer[_NCOL["Gross DL"]]) == pytest.approx(200.0)
    assert float(footer[_NCOL["Netting Amount"]]) == pytest.approx(200.0)
    assert float(footer[_NCOL["Net DA"]]) == pytest.approx(200.0)
    assert float(footer[_NCOL["Net DL"]]) == pytest.approx(0.0)
