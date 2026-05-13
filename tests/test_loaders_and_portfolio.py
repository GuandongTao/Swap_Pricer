"""Block C smoke tests: loaders + portfolio runner end-to-end against sample data."""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from swaps.loaders.excel import ExcelCurveLoader, ExcelFixingLoader
from swaps.loaders.yaml_trades import YamlTradeLoader
from swaps.portfolio import Portfolio


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


@pytest.fixture(scope="module")
def loaders():
    return (
        ExcelCurveLoader(DATA / "curves"),
        ExcelFixingLoader(DATA / "fixings" / "fedfunds.csv"),
        YamlTradeLoader(DATA / "trades"),
    )


def test_curve_loader_returns_sofr_and_ff(loaders):
    cl, _, _ = loaders
    sofr = cl.load(date(2026, 3, 31), "SOFR")
    ff = cl.load(date(2026, 3, 31), "FEDFUNDS")
    assert sofr.name == "SOFR" and ff.name == "FEDFUNDS"
    assert len(sofr.pillars) >= 40
    assert len(ff.pillars) >= 40


def test_curve_loader_unknown_curve_raises(loaders):
    cl, _, _ = loaders
    with pytest.raises(ValueError):
        cl.load(date(2026, 3, 31), "BOGUS")


def test_fixings_loader_returns_history(loaders):
    _, fl, _ = loaders
    h = fl.load("FEDFUNDS")
    assert len(h) > 30  # real samples may be short
    # Pick a recent date that should be in any reasonable fedfunds history
    df = h.to_debug_frame()
    assert not df.empty


def test_trade_loader_loads_all_samples(loaders):
    _, _, tl = loaders
    trades = tl.load_all()
    ids = {t.trade_id for t in trades}
    assert "SWAP_DEBUG_001" in ids


def test_portfolio_runner_produces_all_outputs(loaders, tmp_path):
    cl, fl, tl = loaders
    pf = Portfolio(cl, fl, tl)
    valuations, manifest = pf.run(date(2026, 3, 31), out_dir=tmp_path)
    assert manifest.status == "ok"
    assert len(valuations) >= 1
    trade_ids = {v.trade_id for v in valuations}

    # Files
    assert (tmp_path / "portfolio_2026-03-31.xlsx").exists()
    for tid in trade_ids:
        assert (tmp_path / "detail" / f"{tid}.xlsx").exists()
    for name in ("summary", "floating_cf", "fixed_cf", "curves"):
        assert (tmp_path / "parquet" / "2026-03-31" / f"{name}.parquet").exists()
    assert (tmp_path / "manifest_2026-03-31.json").exists()


def test_portfolio_invariants(loaders, tmp_path):
    cl, fl, tl = loaders
    pf = Portfolio(cl, fl, tl)
    valuations, _ = pf.run(date(2026, 3, 31), out_dir=tmp_path, write_detail=False, write_parquet=False)
    for v in valuations:
        assert v.clean + v.accrued == pytest.approx(v.dirty, abs=1e-6)


def test_summary_parquet_has_identifying_columns(loaders, tmp_path):
    cl, fl, tl = loaders
    pf = Portfolio(cl, fl, tl)
    pf.run(date(2026, 3, 31), out_dir=tmp_path, write_detail=False)
    df = pd.read_parquet(tmp_path / "parquet" / "2026-03-31" / "summary.parquet")
    for col in ("run_id", "val_date", "run_date", "git_sha", "trade_id"):
        assert col in df.columns
    assert df["run_id"].nunique() == 1  # one run id per run
