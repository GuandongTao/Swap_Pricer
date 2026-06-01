"""Month-end-on-weekend/holiday curve fallback.

When a month-end valuation date is itself a non-business day there is no
published market data for it. The curve loaders fall back to the previous
business day's file (one ``Preceding`` hop, skipping weekends + holidays) while
the curve stays anchored at ``val_date``. A missing previous-close file is a
hard error, not a silent roll-back.
"""

from datetime import date

import pytest

from swaps.calendar_us import (
    NY_FED,
    USCalendar,
    is_month_end,
    month_end_curve_date,
)
from swaps.loaders.base import MissingPreviousCloseError
from swaps.loaders.dated import DatedCurveLoader, DatedDFCurveLoader
from swaps.loaders.excel import ExcelCurveLoader

# 2026-01-31 is a Saturday; 2026-01-30 the preceding Friday (a business day).
SAT_MONTH_END = date(2026, 1, 31)
PREV_FRI = date(2026, 1, 30)


# --------------------------------------------------------------- calendar layer
def test_is_month_end():
    assert is_month_end(date(2026, 1, 31))
    assert is_month_end(date(2026, 2, 28))      # 2026 not a leap year
    assert is_month_end(date(2026, 12, 31))
    assert not is_month_end(date(2026, 2, 27))
    assert not is_month_end(date(2026, 1, 30))


def test_fallback_weekend_month_end():
    assert not NY_FED.is_business_day(SAT_MONTH_END)
    assert month_end_curve_date(SAT_MONTH_END) == PREV_FRI


def test_no_fallback_for_business_day_month_end():
    # 2026-03-31 is a Tuesday (used as a normal val_date elsewhere).
    assert NY_FED.is_business_day(date(2026, 3, 31))
    assert month_end_curve_date(date(2026, 3, 31)) is None


def test_no_fallback_for_non_month_end_weekend():
    sat = date(2026, 1, 24)
    assert not NY_FED.is_business_day(sat)
    assert month_end_curve_date(sat) is None


def test_fallback_hops_over_holiday():
    # Force the preceding Friday to be a holiday -> roll back to Thursday.
    cal = USCalendar(extra_holidays={PREV_FRI})
    assert month_end_curve_date(SAT_MONTH_END, cal) == date(2026, 1, 29)


# --------------------------------------------------------------- error contract
def test_missing_previous_close_is_not_filenotfound():
    # Batch classifies FileNotFoundError as a benign skip; a missing
    # previous-close file must escape that path and be a hard error.
    assert issubclass(MissingPreviousCloseError, RuntimeError)
    assert not issubclass(MissingPreviousCloseError, FileNotFoundError)


# ------------------------------------------------------------- ExcelCurveLoader
def _write_market_env(path, sofr, ff):
    lines = ["Name,Property"]  # non-data header row (filtered by TICKER_RE)
    for tenor, r in sofr.items():
        lines.append(f"IR.USD-SOFR-ON.ZERORATE-{tenor}.MID,{r}")
    for tenor, r in ff.items():
        lines.append(f"IR.USD-FEDFUNDS-ON.ZERORATE-{tenor}.MID,{r}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


_SOFR = {"1M": 0.0432, "3M": 0.0421, "1Y": 0.0392, "5Y": 0.0361}
_FF = {"1M": 0.0430, "3M": 0.0419, "1Y": 0.0390, "5Y": 0.0359}


def test_excel_loader_uses_previous_close_file(tmp_path):
    _write_market_env(tmp_path / "market_environment_2026-01-30.csv", _SOFR, _FF)
    ldr = ExcelCurveLoader(tmp_path)
    sofr = ldr.load(SAT_MONTH_END, "SOFR")
    ff = ldr.load(SAT_MONTH_END, "FEDFUNDS")
    # Curve sourced from Friday's file but ANCHORED at the Saturday val_date.
    assert sofr.val_date == SAT_MONTH_END
    assert ff.val_date == SAT_MONTH_END
    assert len(sofr.pillars) == len(_SOFR)


def test_excel_loader_missing_previous_close_hard_errors(tmp_path):
    ldr = ExcelCurveLoader(tmp_path)  # empty dir, no Friday file
    with pytest.raises(MissingPreviousCloseError):
        ldr.load(SAT_MONTH_END, "SOFR")


def test_excel_loader_non_month_end_weekend_filenotfound(tmp_path):
    ldr = ExcelCurveLoader(tmp_path)
    with pytest.raises(FileNotFoundError):
        ldr.load(date(2026, 1, 24), "SOFR")  # ordinary Saturday -> normal skip path


def test_excel_loader_business_day_unchanged(tmp_path):
    _write_market_env(tmp_path / "market_environment_2026-03-31.csv", _SOFR, _FF)
    ldr = ExcelCurveLoader(tmp_path)
    sofr = ldr.load(date(2026, 3, 31), "SOFR")
    assert sofr.val_date == date(2026, 3, 31)


# ------------------------------------------------------------- dated loaders
def _write_dated(path, rows):
    path.write_text("\n".join(f"{d.isoformat()},{v}" for d, v in rows) + "\n", encoding="utf-8")


def test_dated_loader_previous_close_drops_colliding_pillar(tmp_path):
    # Friday file with an absolute ON pillar dated on the Saturday val_date;
    # re-anchoring must drop it (ZeroCurve rejects pillar_date <= val_date).
    rows = [(SAT_MONTH_END, 0.044), (date(2026, 3, 2), 0.043), (date(2027, 1, 29), 0.039)]
    _write_dated(tmp_path / "sofr_2026-01-30.csv", rows)
    _write_dated(tmp_path / "ff_2026-01-30.csv", rows)
    ldr = DatedCurveLoader(tmp_path)
    c = ldr.load(SAT_MONTH_END, "SOFR")
    assert c.val_date == SAT_MONTH_END
    assert all(p.pillar_date > SAT_MONTH_END for p in c.pillars)
    assert len(c.pillars) == 2  # the SAT_MONTH_END pillar was dropped


def test_dated_loader_missing_previous_close_hard_errors(tmp_path):
    ldr = DatedCurveLoader(tmp_path)
    with pytest.raises(MissingPreviousCloseError):
        ldr.load(SAT_MONTH_END, "SOFR")


def test_dated_df_loader_previous_close(tmp_path):
    rows = [(SAT_MONTH_END, 0.9999), (date(2026, 3, 2), 0.9960), (date(2027, 1, 29), 0.9600)]
    _write_dated(tmp_path / "sofr_df_2026-01-30.csv", rows)
    _write_dated(tmp_path / "ff_df_2026-01-30.csv", rows)
    ldr = DatedDFCurveLoader(tmp_path)
    c = ldr.load(SAT_MONTH_END, "SOFR")
    assert c.val_date == SAT_MONTH_END
    assert all(p.pillar_date > SAT_MONTH_END for p in c.pillars)


def test_dated_df_loader_missing_previous_close_hard_errors(tmp_path):
    ldr = DatedDFCurveLoader(tmp_path)
    with pytest.raises(MissingPreviousCloseError):
        ldr.load(SAT_MONTH_END, "SOFR")
