from datetime import date, timedelta

import numpy as np
import pytest

from swaps.curve import ZeroCurve, tenor_to_date
from swaps.rate_quoting import ContinuousACT360, SimpleACT360


VAL = date(2026, 3, 31)


def test_tenor_to_date():
    # Strict ACT/360 day math: D=N, W=7N, M=30N, Y=360N
    assert tenor_to_date(VAL, "ON") == date(2026, 4, 1)
    assert tenor_to_date(VAL, "TN") == date(2026, 4, 2)
    assert tenor_to_date(VAL, "1W") == date(2026, 4, 7)             # +7 days
    assert tenor_to_date(VAL, "1M") == date(2026, 4, 30)            # +30 days
    assert tenor_to_date(VAL, "2M") == date(2026, 5, 30)            # +60 days
    assert tenor_to_date(VAL, "1Y") == VAL + timedelta(days=360)    # +360 days  (NOT +1 cal year)
    assert tenor_to_date(VAL, "5Y") == VAL + timedelta(days=1800)   # +1800 days
    assert tenor_to_date(VAL, "50Y") == VAL + timedelta(days=18000)


def test_pillar_round_trip_at_pillar_dates():
    """DF computed at a pillar date should round-trip exactly to its zero rate."""
    pillars = {"1Y": 0.04, "5Y": 0.045, "10Y": 0.043}
    c = ZeroCurve(VAL, pillars, ContinuousACT360())
    for p in c.pillars:
        days = (p.pillar_date - VAL).days
        rt_rate = ContinuousACT360().df_to_rate(c.df(p.pillar_date), days)
        assert rt_rate == pytest.approx(p.zero_rate, abs=1e-12)


def test_flat_curve_implies_flat_continuous_forward():
    """Log-linear interp on a flat continuously-quoted curve gives flat instantaneous fwd."""
    pillars = {"1M": 0.05, "1Y": 0.05, "5Y": 0.05, "10Y": 0.05}
    c = ZeroCurve(VAL, pillars, ContinuousACT360())
    # Daily implied forward in continuous-ACT360 land: should be ~exp(0.05/360)-1 each day,
    # i.e. simple forward ~= e^(0.05/360) - 1 -> annualized simple rate ~= 0.05.
    f = c.forward(date(2026, 6, 1), date(2026, 6, 2))
    expected = (np.exp(0.05 / 360) - 1.0) * 360.0
    assert f == pytest.approx(expected, abs=1e-10)


def test_value_date_df_is_one():
    pillars = {"1Y": 0.04}
    c = ZeroCurve(VAL, pillars, ContinuousACT360())
    assert c.df(VAL) == pytest.approx(1.0, abs=1e-15)


def test_log_linear_interp_midpoint():
    """At the midpoint between two pillars (in days), log(DF) should be the average of endpoints."""
    pillars = {"1Y": 0.04, "5Y": 0.05}
    c = ZeroCurve(VAL, pillars, ContinuousACT360())
    d1, d2 = tenor_to_date(VAL, "1Y"), tenor_to_date(VAL, "5Y")
    mid_days = ((d1 - VAL).days + (d2 - VAL).days) // 2
    mid_date = VAL + timedelta(days=mid_days)
    log_mid = np.log(c.df(mid_date))
    log_avg = 0.5 * (np.log(c.df(d1)) + np.log(c.df(d2)))
    # Under strict ACT/360 day math (1Y=360, 5Y=1800), midpoint is exact (1080 days)
    assert abs(log_mid - log_avg) < 1e-12


def test_negative_offset_raises():
    pillars = {"1Y": 0.04}
    c = ZeroCurve(VAL, pillars, ContinuousACT360())
    with pytest.raises(ValueError):
        c.df(date(2026, 3, 30))


def test_extrapolation_past_last_pillar_continuous():
    """Past last pillar, log-DF extrapolates linearly using last segment slope."""
    pillars = {"5Y": 0.05, "10Y": 0.05}
    c = ZeroCurve(VAL, pillars, ContinuousACT360())
    # Flat curve -> extrapolation should remain on the same line
    d20 = tenor_to_date(VAL, "20Y")
    days = (d20 - VAL).days
    expected_log_df = -0.05 * days / 360.0
    assert np.log(c.df(d20)) == pytest.approx(expected_log_df, abs=1e-10)


def test_to_debug_frame_columns():
    pillars = {"1W": 0.036, "1Y": 0.04}
    c = ZeroCurve(VAL, pillars, ContinuousACT360())
    df = c.to_debug_frame()
    assert list(df.columns) == ["tenor", "pillar_date", "days", "zero_rate", "df"]
    assert len(df) == 2
    assert df["days"].iloc[0] < df["days"].iloc[1]  # sorted


def test_df_grid_debug_columns_and_length():
    pillars = {"1Y": 0.04}
    c = ZeroCurve(VAL, pillars, ContinuousACT360())
    grid = c.df_grid_debug(VAL, VAL + timedelta(days=10))
    assert list(grid.columns) == ["date", "df", "log_df", "implied_daily_fwd"]
    assert len(grid) == 11  # inclusive


def test_simple_act360_quoting_changes_dfs():
    pillars = {"1Y": 0.05}
    c_cont = ZeroCurve(VAL, pillars, ContinuousACT360())
    c_simp = ZeroCurve(VAL, pillars, SimpleACT360())
    # Same input rate but different conventions -> distinct DFs at the pillar
    assert c_cont.df(tenor_to_date(VAL, "1Y")) != c_simp.df(tenor_to_date(VAL, "1Y"))
