"""CsvTradeLoader: batch trade entry via CSV."""

from datetime import date
from pathlib import Path

import pytest

from swaps.loaders.csv_trades import CsvTradeLoader


CSV_BODY = """# header comment
trade_id,notional,pay_fixed,fixed_rate,start_date,maturity_date,fixed_frequency,fixed_daycount,floating_daycount,floating_spread,payment_delay_bdays,description
T001,1000000,false,0.0400,2026-06-15,2031-06-15,1Y,ACT/360,ACT/360,0,0,5Y rcv-fixed
T002,2000000,true,0.0350,2026-06-15,2031-06-15,3M,ACT/360,ACT/360,0.0025,2,5Y pay-fixed with spread
T003,500000,false,0.0500,2026-06-15,2027-06-15,1M,30/360,ACT/360,0,2,1Y rcv-fixed monthly 30/360 fixed
"""


def test_loads_multiple_rows(tmp_path):
    p = tmp_path / "batch.csv"
    p.write_text(CSV_BODY, encoding="utf-8")
    trades = CsvTradeLoader(tmp_path).load_all()
    assert [t.trade_id for t in trades] == ["T001", "T002", "T003"]


def test_parses_field_types(tmp_path):
    (tmp_path / "batch.csv").write_text(CSV_BODY, encoding="utf-8")
    trades = {t.trade_id: t for t in CsvTradeLoader(tmp_path).load_all()}
    t1 = trades["T001"]
    assert t1.notional == 1_000_000.0
    assert t1.pay_fixed is False
    assert t1.fixed_rate == 0.04
    assert t1.start_date == date(2026, 6, 15)
    assert t1.maturity_date == date(2031, 6, 15)
    assert t1.fixed_frequency == "1Y"
    assert t1.floating_spread == 0.0


def test_defaults_when_optional_columns_omitted(tmp_path):
    (tmp_path / "batch.csv").write_text(
        "trade_id,notional,pay_fixed,fixed_rate,start_date,maturity_date,fixed_frequency,fixed_daycount\n"
        "MIN,100,true,0.05,2026-06-15,2027-06-15,1Y,ACT/360\n",
        encoding="utf-8",
    )
    t = CsvTradeLoader(tmp_path).load("MIN")
    assert t.floating_daycount == "ACT/360"
    assert t.floating_spread == 0.0
    assert t.fixed_calculation_calendar == "NY_FED"
    assert t.floating_calculation_calendar == "NY_FED"
    assert t.floating_fixing_calendar == "NY_FED"
    assert t.fixed_payment_delay_bdays == 0
    assert t.floating_payment_delay_bdays == 0
    assert t.floating_lockout_bdays == 0
    assert t.fixed_bus_day_adj == "ModifiedFollowing"
    assert t.floating_bus_day_adj == "ModifiedFollowing"
    assert t.fixed_roll_convention == "forward_eom"
    assert t.fixed_adjust == "acc_and_pay"


def test_skip_blank_rows_and_comments(tmp_path):
    (tmp_path / "batch.csv").write_text(
        "# comment line\n"
        "trade_id,notional,pay_fixed,fixed_rate,start_date,maturity_date,fixed_frequency,fixed_daycount\n"
        "T1,100,true,0.04,2026-06-15,2027-06-15,1Y,ACT/360\n"
        "\n"
        ",,,,,,,\n"
        "T2,200,false,0.05,2026-06-15,2027-06-15,1Y,ACT/360\n",
        encoding="utf-8",
    )
    trades = CsvTradeLoader(tmp_path).load_all()
    assert [t.trade_id for t in trades] == ["T1", "T2"]


def test_underscore_prefixed_files_are_ignored(tmp_path):
    (tmp_path / "_template.csv").write_text(
        "trade_id,notional,pay_fixed,fixed_rate,start_date,maturity_date,fixed_frequency,fixed_daycount\n"
        "TEMPLATE,100,true,0.04,2026-06-15,2027-06-15,1Y,ACT/360\n",
        encoding="utf-8",
    )
    (tmp_path / "active.csv").write_text(
        "trade_id,notional,pay_fixed,fixed_rate,start_date,maturity_date,fixed_frequency,fixed_daycount\n"
        "REAL,100,true,0.04,2026-06-15,2027-06-15,1Y,ACT/360\n",
        encoding="utf-8",
    )
    trades = CsvTradeLoader(tmp_path).load_all()
    assert {t.trade_id for t in trades} == {"REAL"}
