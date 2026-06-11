"""Parquet output: same frames as Excel, machine-readable, DB-loadable."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from .curve import ZeroCurve
from .io_excel import _curves_frame, _stack_cashflows, _summary_row
from .pricer import SwapValuation


def write_parquet_outputs(
    out_dir: str | Path,
    valuations: list[SwapValuation],
    curves: dict[str, ZeroCurve],
    run_id: str,
    run_date: datetime,
    git_sha: str,
) -> dict[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    val_date = valuations[0].val_date if valuations else None
    summary = pd.DataFrame([_summary_row(v, run_id, run_date, git_sha) for v in valuations])
    fl = _stack_cashflows(valuations, "floating_cf", run_id, run_date, git_sha)
    fx = _stack_cashflows(valuations, "fixed_cf", run_id, run_date, git_sha)
    curves_df = _curves_frame(curves, run_id, val_date, run_date, git_sha)
    paths: dict[str, Path] = {}
    for name, df in (("summary", summary), ("floating_cf", fl), ("fixed_cf", fx), ("curves", curves_df)):
        p = out_dir / f"{name}.parquet"
        df.to_parquet(p, index=False)
        paths[name] = p
    return paths
