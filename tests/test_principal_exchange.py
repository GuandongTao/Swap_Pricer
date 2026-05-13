"""Per-leg principal-exchange policy: none / start / end / both."""

from datetime import date

import pandas as pd
import pytest

from swaps.calendar_us import NY_FED
from swaps.conventions import ACT_360
from swaps.curve import ZeroCurve
from swaps.fixings import FixingHistory
from swaps.legs.fixed_leg import FixedLeg
from swaps.legs.floating_leg_ois import OISFloatingLeg
from swaps.notional import ConstantNotional
from swaps.rate_quoting import ContinuousACT360
from swaps.schedule import generate_schedule

VAL = date(2026, 3, 31)
N = 1_000_000


def _curve(rate: float = 0.04) -> ZeroCurve:
    return ZeroCurve(VAL, {"1M": rate, "1Y": rate, "5Y": rate, "10Y": rate}, ContinuousACT360())


def _make_schedule():
    return generate_schedule(
        effective_date=date(2026, 6, 15),
        termination_date=date(2031, 6, 15),
        frequency="1Y",
        calendar=NY_FED,
        payment_delay_bdays=2,
    )


# -------------------------------------------------------------- FixedLeg
def test_fixed_leg_default_no_principal_rows():
    sch = _make_schedule()
    leg = FixedLeg(sch, ConstantNotional(N), 0.04, ACT_360)
    cf = leg.cashflows(VAL, _curve())
    assert set(cf["flow_type"]) == {"coupon"}


def test_fixed_leg_principal_end():
    sch = _make_schedule()
    leg = FixedLeg(sch, ConstantNotional(N), 0.04, ACT_360, principal_exchange="end")
    cf = leg.cashflows(VAL, _curve())
    end_row = cf[cf["flow_type"] == "principal_end"].iloc[0]
    assert end_row["payment_amount"] == N
    assert end_row["payment_date"] == sch[-1].payment_date
    # PV increases by N * DF(final_pay)
    c = _curve()
    base_pv = FixedLeg(sch, ConstantNotional(N), 0.04, ACT_360).pv(VAL, c)
    pv_with = leg.pv(VAL, c)
    assert pv_with - base_pv == pytest.approx(N * c.df(sch[-1].payment_date), abs=1e-6)


def test_fixed_leg_principal_start_at_forward_date():
    """When start_date is in the future, principal_start row contributes -N * DF(start) to PV."""
    sch = _make_schedule()
    leg = FixedLeg(sch, ConstantNotional(N), 0.04, ACT_360, principal_exchange="start")
    c = _curve()
    base_pv = FixedLeg(sch, ConstantNotional(N), 0.04, ACT_360).pv(VAL, c)
    pv_with = leg.pv(VAL, c)
    assert pv_with - base_pv == pytest.approx(-N * c.df(sch[0].start), abs=1e-6)


def test_fixed_leg_principal_both():
    sch = _make_schedule()
    leg = FixedLeg(sch, ConstantNotional(N), 0.04, ACT_360, principal_exchange="both")
    cf = leg.cashflows(VAL, _curve())
    assert (cf["flow_type"] == "principal_start").sum() == 1
    assert (cf["flow_type"] == "principal_end").sum() == 1
    assert (cf["flow_type"] == "coupon").sum() == len(sch)


def test_fixed_leg_invalid_principal_exchange_raises():
    sch = _make_schedule()
    with pytest.raises(ValueError):
        FixedLeg(sch, ConstantNotional(N), 0.04, ACT_360, principal_exchange="bogus")


# -------------------------------------------------------------- FloatingLeg
def _float_leg(pex: str) -> OISFloatingLeg:
    sch = _make_schedule()
    return OISFloatingLeg(
        schedule=sch,
        notional=ConstantNotional(N),
        projection_curve=_curve(),
        fixings=FixingHistory(),
        daycount=ACT_360,
        fixing_calendar=NY_FED,
        principal_exchange=pex,
    )


def test_floating_leg_default_no_principal_rows():
    cf = _float_leg("none").cashflows(VAL, _curve())
    assert set(cf["flow_type"]) == {"coupon"}


def test_floating_leg_principal_end_in_cashflows():
    leg = _float_leg("end")
    cf = leg.cashflows(VAL, _curve())
    end = cf[cf["flow_type"] == "principal_end"].iloc[0]
    assert end["period_cashflow"] == N
    # PV impact
    c = _curve()
    pv_base = _float_leg("none").pv(VAL, c)
    pv_end = leg.pv(VAL, c)
    assert pv_end - pv_base == pytest.approx(N * c.df(leg.schedule[-1].payment_date), abs=1e-3)


def test_floating_leg_principal_both_in_monthly_view():
    leg = _float_leg("both")
    pcf = leg.period_cashflows(VAL, _curve())
    flows = list(pcf["flow_type"])
    assert flows[0] == "principal_start"
    assert flows[-1] == "principal_end"
    assert flows.count("coupon") == len(leg.schedule)


def test_floating_leg_invalid_principal_exchange_raises():
    with pytest.raises(ValueError):
        OISFloatingLeg(
            schedule=_make_schedule(),
            notional=ConstantNotional(N),
            projection_curve=_curve(),
            fixings=FixingHistory(),
            daycount=ACT_360,
            fixing_calendar=NY_FED,
            principal_exchange="weird",
        )


def test_bilateral_principal_exchange_pv_neutral():
    """Both legs with principal_exchange='both' should net to zero in dirty PV
    -- the bilateral exchange is a wash for the swap holder."""
    from swaps.market_data import MarketData
    from swaps.pricer import SwapPricer
    from swaps.swap import Swap

    sch = _make_schedule()
    c = _curve()
    md = MarketData(VAL, c, c, FixingHistory())

    fixed_plain = FixedLeg(sch, ConstantNotional(N), 0.04, ACT_360)
    float_plain = OISFloatingLeg(sch, ConstantNotional(N), c, FixingHistory(), ACT_360, NY_FED)
    swap_plain = Swap("PLAIN", fixed_plain, float_plain, pay_fixed=False)

    fixed_pex = FixedLeg(sch, ConstantNotional(N), 0.04, ACT_360, principal_exchange="both")
    float_pex = OISFloatingLeg(sch, ConstantNotional(N), c, FixingHistory(), ACT_360, NY_FED, principal_exchange="both")
    swap_pex = Swap("PEX", fixed_pex, float_pex, pay_fixed=False)

    pricer = SwapPricer()
    base = pricer.price(swap_plain, md)
    with_pex = pricer.price(swap_pex, md)
    # Same dirty: bilateral exchange cancels for the swap holder
    assert with_pex.dirty == pytest.approx(base.dirty, abs=1e-3)


def test_yaml_loader_passes_through_principal_exchange(tmp_path):
    from swaps.loaders.yaml_trades import YamlTradeLoader

    (tmp_path / "X.yaml").write_text(
        """
trade_id: PEX_TEST
notional: 1000000
pay_fixed: false
fixed_rate: 0.04
start_date: 2026-06-15
maturity_date: 2031-06-15
fixed_frequency: 1Y
fixed_daycount: ACT/360
fixed_principal_exchange: end
floating_principal_exchange: start
""",
        encoding="utf-8",
    )
    td = YamlTradeLoader(tmp_path).load("PEX_TEST")
    assert td.fixed_principal_exchange == "end"
    assert td.floating_principal_exchange == "start"


def test_csv_loader_passes_through_principal_exchange(tmp_path):
    from swaps.loaders.csv_trades import CsvTradeLoader

    (tmp_path / "X.csv").write_text(
        "trade_id,notional,pay_fixed,fixed_rate,start_date,maturity_date,fixed_frequency,fixed_daycount,"
        "fixed_principal_exchange,floating_principal_exchange\n"
        "PEX_CSV,1000000,false,0.04,2026-06-15,2031-06-15,1Y,ACT/360,end,both\n",
        encoding="utf-8",
    )
    td = CsvTradeLoader(tmp_path).load("PEX_CSV")
    assert td.fixed_principal_exchange == "end"
    assert td.floating_principal_exchange == "both"
