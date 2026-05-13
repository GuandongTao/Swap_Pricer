from datetime import date

import pandas as pd

from swaps.fixings import FixingHistory


def test_get_returns_none_for_missing():
    h = FixingHistory()
    assert h.get(date(2026, 1, 1)) is None


def test_get_known_rate():
    h = FixingHistory({date(2026, 1, 1): 0.05})
    assert h.get(date(2026, 1, 1)) == 0.05
    assert date(2026, 1, 1) in h


def test_accepts_pandas_series():
    s = pd.Series([0.04, 0.05], index=pd.to_datetime(["2026-01-01", "2026-01-02"]))
    h = FixingHistory(s)
    assert h.get(date(2026, 1, 1)) == 0.04
    assert h.get(date(2026, 1, 2)) == 0.05


def test_to_debug_frame_sorted():
    h = FixingHistory({date(2026, 1, 2): 0.05, date(2026, 1, 1): 0.04})
    df = h.to_debug_frame()
    assert list(df.columns) == ["date", "rate"]
    assert df["date"].tolist() == [date(2026, 1, 1), date(2026, 1, 2)]
