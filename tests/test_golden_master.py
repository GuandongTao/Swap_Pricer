"""Golden-master regression test.

Pins the canonical pricer output (per-trade summary numbers) for the sample
portfolio on 2026-03-31. Any unintended numeric drift fails this test with the
exact diff.

To intentionally update the baseline after a deliberate behavior change, run::

    REGENERATE_GOLDEN=1 pytest tests/test_golden_master.py
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import pytest

from swaps.loaders.excel import ExcelCurveLoader, ExcelFixingLoader
from swaps.loaders.yaml_trades import YamlTradeLoader
from swaps.portfolio import Portfolio


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
GOLDEN_FILE = Path(__file__).parent / "golden" / "portfolio_2026-03-31.json"

FIELDS = ("clean", "dirty", "accrued", "dv01", "pv_fixed", "pv_floating")


def _run_portfolio(tmp_path: Path) -> dict[str, dict[str, float]]:
    pf = Portfolio(
        ExcelCurveLoader(DATA / "curves"),
        ExcelFixingLoader(DATA / "fixings" / "fixing_cali_USD-FEDFUNDS-ON.csv"),
        YamlTradeLoader(DATA / "trades"),
    )
    valuations, _ = pf.run(
        date(2026, 3, 31),
        out_dir=tmp_path,
        write_detail=False,
        write_parquet=False,
    )
    return {
        v.trade_id: {f: float(getattr(v, f)) for f in FIELDS}
        for v in valuations
    }


def test_golden_master_matches(tmp_path):
    if os.environ.get("REGENERATE_GOLDEN"):
        actual = _run_portfolio(tmp_path)
        GOLDEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN_FILE.write_text(
            json.dumps({"val_date": "2026-03-31", "trades": actual}, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        pytest.skip(f"Regenerated golden file at {GOLDEN_FILE}")

    if not GOLDEN_FILE.exists():
        pytest.skip(
            f"Golden file not present at {GOLDEN_FILE}. Golden snapshots are derived "
            f"from real market data and not committed. To pin one locally:\n"
            f"  REGENERATE_GOLDEN=1 pytest tests/test_golden_master.py"
        )
    actual = _run_portfolio(tmp_path)
    expected = json.loads(GOLDEN_FILE.read_text(encoding="utf-8"))["trades"]

    assert set(actual) == set(expected), (
        f"Trade-id set drift; actual={set(actual)}, expected={set(expected)}"
    )
    diffs = []
    for tid, exp_vals in expected.items():
        for f in FIELDS:
            a = actual[tid][f]
            e = exp_vals[f]
            # Tight: ~1e-9 relative for nonzero, absolute 1e-9 for zero
            if e == 0:
                if abs(a) > 1e-9:
                    diffs.append(f"{tid}.{f}: expected 0, got {a:.6f}")
            elif abs(a - e) / max(abs(e), 1.0) > 1e-9:
                diffs.append(f"{tid}.{f}: expected {e:.10f}, got {a:.10f} (diff {a-e:.4e})")
    assert not diffs, "Golden-master drift:\n" + "\n".join(diffs)
