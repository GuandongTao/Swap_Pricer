"""DF-direct curve path: ZeroCurve.from_dated_dfs + DatedDFCurveLoader.

Activated by the CLI ``--pillar-dates-df`` flag. The pricer bypasses
``RateQuoting`` entirely; the supplied discount factors feed straight into
the log-linear interpolation.
"""

import math
from datetime import date

import pytest

from swaps.curve import ZeroCurve, tenor_to_date
from swaps.loaders.dated import DatedDFCurveLoader
from swaps.rate_quoting import ContinuousACT360


VAL = date(2026, 3, 31)


# ---------------------------------------------------------------- from_dated_dfs
def test_from_dated_dfs_matches_rate_path_when_dfs_consistent():
    """Build the curve via rates, read off its pillar DFs, then build a second
    curve directly from those DFs. df() must agree everywhere (no quoting
    re-application; same log-linear interpolation)."""
    rate_pillars = {"1M": 0.0432, "3M": 0.0421, "6M": 0.0410, "1Y": 0.0392, "5Y": 0.0361}
    c_rate = ZeroCurve(VAL, rate_pillars, ContinuousACT360())
    df_pillars = {p.pillar_date: p.df for p in c_rate.pillars}
    c_df = ZeroCurve.from_dated_dfs(VAL, df_pillars, name="X")

    for d in [date(2026, 6, 30), date(2027, 3, 31), date(2030, 12, 31), date(2031, 3, 31)]:
        assert c_df.df(d) == pytest.approx(c_rate.df(d), rel=1e-12)


def test_from_dated_dfs_marks_zero_rate_nan():
    """Quoting is bypassed -> Pillar.zero_rate is NaN (no convention applied)."""
    c = ZeroCurve.from_dated_dfs(VAL, {date(2027, 3, 31): 0.96})
    assert all(math.isnan(p.zero_rate) for p in c.pillars)


def test_from_dated_dfs_rejects_nonpositive_df():
    with pytest.raises(ValueError, match="DF must be > 0"):
        ZeroCurve.from_dated_dfs(VAL, {date(2027, 3, 31): 0.0})
    with pytest.raises(ValueError, match="DF must be > 0"):
        ZeroCurve.from_dated_dfs(VAL, {date(2027, 3, 31): -0.5})


def test_from_dated_dfs_rejects_pillar_at_or_before_val_date():
    with pytest.raises(ValueError):
        ZeroCurve.from_dated_dfs(VAL, {VAL: 1.0})


def test_from_dated_dfs_rejects_empty():
    with pytest.raises(ValueError):
        ZeroCurve.from_dated_dfs(VAL, {})


# ---------------------------------------------------------------- bumped() on all paths
def test_bumped_works_on_df_direct_curve_continuous_equivalence():
    c = ZeroCurve.from_dated_dfs(VAL, {tenor_to_date(VAL, "1Y"): 0.96, tenor_to_date(VAL, "5Y"): 0.83})
    bumped = c.bumped(1e-4)
    # Continuous-ACT/360 shift: DF_new = DF * exp(-delta * days / 360)
    for p_orig, p_new in zip(c.pillars, bumped.pillars):
        expected = p_orig.df * math.exp(-1e-4 * p_orig.days / 360.0)
        assert p_new.df == pytest.approx(expected, rel=1e-14)


def test_bumped_works_on_dated_rate_curve():
    """The dated-rate path also uses ISO-date pillar tenors; bumped() must
    still work (it used to call the tenor-keyed constructor which would
    fail to parse ISO dates as tenors)."""
    pillars = {tenor_to_date(VAL, "1Y"): 0.04, tenor_to_date(VAL, "5Y"): 0.036}
    c = ZeroCurve.from_dated_pillars(VAL, pillars, ContinuousACT360())
    bumped = c.bumped(1e-4)
    # DFs after bump should be the rate_to_df under bumped rates
    rq = ContinuousACT360()
    for p_orig, p_new in zip(c.pillars, bumped.pillars):
        expected = rq.rate_to_df(p_orig.zero_rate + 1e-4, p_orig.days)
        assert p_new.df == pytest.approx(expected, rel=1e-14)


# ---------------------------------------------------------------- DatedDFCurveLoader
def _write(path, rows):
    path.write_text("\n".join(f"{d.isoformat()},{v}" for d, v in rows) + "\n", encoding="utf-8")


def test_df_loader_reads_both_curves(tmp_path):
    sofr = [(date(2026, 4, 30), 0.9970), (date(2026, 6, 30), 0.9925), (date(2027, 3, 31), 0.9620)]
    ff = [(date(2026, 4, 30), 0.9972), (date(2026, 6, 30), 0.9928), (date(2027, 3, 31), 0.9625)]
    _write(tmp_path / "sofr_df_2026-03-31.csv", sofr)
    _write(tmp_path / "ff_df_2026-03-31.csv", ff)
    ldr = DatedDFCurveLoader(tmp_path)
    c_sofr = ldr.load(VAL, "SOFR")
    c_ff = ldr.load(VAL, "FEDFUNDS")
    assert c_sofr.name == "SOFR" and c_ff.name == "FEDFUNDS"
    assert [p.df for p in c_sofr.pillars] == [v for _, v in sofr]


def test_df_loader_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        DatedDFCurveLoader(tmp_path).load(VAL, "SOFR")


def test_df_loader_rejects_nonpositive_df(tmp_path):
    p = tmp_path / "sofr_df_2026-03-31.csv"
    p.write_text("2026-06-30,0.99\n2027-06-30,0.0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="DF must be > 0"):
        DatedDFCurveLoader(tmp_path).load(VAL, "SOFR")


def test_df_loader_rejects_duplicate_pillar(tmp_path):
    p = tmp_path / "sofr_df_2026-03-31.csv"
    p.write_text("2026-06-30,0.99\n2026-06-30,0.98\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        DatedDFCurveLoader(tmp_path).load(VAL, "SOFR")


def test_df_loader_skips_blank_lines(tmp_path):
    p = tmp_path / "sofr_df_2026-03-31.csv"
    p.write_text("2026-06-30,0.99\n\n2027-06-30,0.96\n\n", encoding="utf-8")
    c = DatedDFCurveLoader(tmp_path).load(VAL, "SOFR")
    assert len(c.pillars) == 2


# ---------------------------------------------------------------- CLI mutex
def test_cli_pillar_flags_mutually_exclusive():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "pp_script", Path(__file__).resolve().parents[1] / "scripts" / "price_portfolio.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with pytest.raises(SystemExit) as ei:
        mod.main(["--val-date", "2026-03-31", "--pillar-dates", "--pillar-dates-df"])
    assert ei.value.code == 2  # argparse mutex violation
