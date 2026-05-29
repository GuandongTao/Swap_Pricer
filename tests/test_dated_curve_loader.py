"""Dated-pillars curve loader + ZeroCurve.from_dated_pillars round-trip.

Activated by the CLI ``--pillar-dates`` flag in production.
"""

from datetime import date

import pytest

from swaps.curve import ZeroCurve, tenor_to_date
from swaps.loaders.dated import DatedCurveLoader
from swaps.rate_quoting import ContinuousACT360


VAL = date(2026, 3, 31)


def test_from_dated_pillars_matches_tenor_path():
    """Same pillars expressed as tenors vs explicit dates must yield identical DFs."""
    tenor_pillars = {"1M": 0.0432, "3M": 0.0421, "6M": 0.0410, "1Y": 0.0392, "5Y": 0.0361}
    dated_pillars = {tenor_to_date(VAL, t): r for t, r in tenor_pillars.items()}

    c_tenor = ZeroCurve(VAL, tenor_pillars, ContinuousACT360(), name="A")
    c_dated = ZeroCurve.from_dated_pillars(VAL, dated_pillars, ContinuousACT360(), name="A")

    # Same pillar dates and DFs to floating-point precision.
    assert [p.pillar_date for p in c_tenor.pillars] == [p.pillar_date for p in c_dated.pillars]
    for d in [date(2026, 6, 30), date(2027, 3, 31), date(2030, 12, 31)]:
        assert c_dated.df(d) == pytest.approx(c_tenor.df(d), rel=1e-12)


def test_from_dated_pillars_rejects_pillar_at_or_before_val_date():
    with pytest.raises(ValueError):
        ZeroCurve.from_dated_pillars(VAL, {VAL: 0.04}, ContinuousACT360())
    with pytest.raises(ValueError):
        ZeroCurve.from_dated_pillars(VAL, {date(2026, 3, 30): 0.04}, ContinuousACT360())


def test_from_dated_pillars_rejects_empty():
    with pytest.raises(ValueError):
        ZeroCurve.from_dated_pillars(VAL, {}, ContinuousACT360())


# ---------------------------------------------------------------- DatedCurveLoader
def _write_curve(path, rows):
    """Write a no-header CSV: date,rate."""
    path.write_text("\n".join(f"{d.isoformat()},{r}" for d, r in rows) + "\n", encoding="utf-8")


def test_dated_loader_reads_both_curves(tmp_path):
    sofr = [(date(2026, 4, 30), 0.0440), (date(2026, 6, 30), 0.0420), (date(2027, 3, 31), 0.0390)]
    ff = [(date(2026, 4, 30), 0.0438), (date(2026, 6, 30), 0.0418), (date(2027, 3, 31), 0.0388)]
    _write_curve(tmp_path / "sofr_2026-03-31.csv", sofr)
    _write_curve(tmp_path / "ff_2026-03-31.csv", ff)

    ldr = DatedCurveLoader(tmp_path)
    c_sofr = ldr.load(VAL, "SOFR")
    c_ff = ldr.load(VAL, "FEDFUNDS")
    assert c_sofr.name == "SOFR" and c_ff.name == "FEDFUNDS"
    assert [p.pillar_date for p in c_sofr.pillars] == [d for d, _ in sofr]
    assert [p.zero_rate for p in c_sofr.pillars] == [r for _, r in sofr]


def test_dated_loader_accepts_ff_aliases(tmp_path):
    _write_curve(tmp_path / "ff_2026-03-31.csv", [(date(2026, 4, 30), 0.04)])
    ldr = DatedCurveLoader(tmp_path)
    # All three names route to the ff_ file
    assert ldr.load(VAL, "FF").name == "FEDFUNDS"
    assert ldr.load(VAL, "FEDFUNDS").name == "FEDFUNDS"
    assert ldr.load(VAL, "FED_FUNDS").name == "FEDFUNDS"


def test_dated_loader_missing_file_raises(tmp_path):
    ldr = DatedCurveLoader(tmp_path)
    with pytest.raises(FileNotFoundError):
        ldr.load(VAL, "SOFR")


def test_dated_loader_rejects_unknown_curve_name(tmp_path):
    ldr = DatedCurveLoader(tmp_path)
    with pytest.raises(ValueError):
        ldr.load(VAL, "BOGUS")


def test_dated_loader_rejects_duplicate_pillar(tmp_path):
    p = tmp_path / "sofr_2026-03-31.csv"
    p.write_text("2026-06-30,0.04\n2026-06-30,0.05\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        DatedCurveLoader(tmp_path).load(VAL, "SOFR")


def test_dated_loader_rejects_bad_row(tmp_path):
    p = tmp_path / "sofr_2026-03-31.csv"
    p.write_text("2026-06-30,0.04\nnot_a_date,0.05\n", encoding="utf-8")
    with pytest.raises(ValueError):
        DatedCurveLoader(tmp_path).load(VAL, "SOFR")


def test_dated_loader_skips_blank_lines(tmp_path):
    p = tmp_path / "sofr_2026-03-31.csv"
    p.write_text("2026-06-30,0.04\n\n2027-06-30,0.038\n\n", encoding="utf-8")
    c = DatedCurveLoader(tmp_path).load(VAL, "SOFR")
    assert len(c.pillars) == 2
