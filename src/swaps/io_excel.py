"""Excel output writers."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .curve import ZeroCurve
from .pricer import SwapValuation


def _summary_row(v: SwapValuation, run_id: str, run_date, git_sha: str) -> dict:
    m = v.meta or {}
    return {
        "run_id": run_id,
        "val_date": v.val_date,
        "run_date": run_date,
        "git_sha": git_sha,
        "trade_id": v.trade_id,
        "id": m.get("id"),
        "notional": m.get("notional"),
        "fixed_rate": m.get("fixed_rate"),
        "start_date": m.get("start_date"),
        "maturity_date": m.get("maturity_date"),
        "pv_fixed": v.pv_fixed,
        "pv_floating": v.pv_floating,
        "par_rate": v.par_rate,
        "rate_diff_bp": v.rate_diff_bp,
        "clean": v.clean,
        "dirty": v.dirty,
        "accrued": v.accrued,
        "dv01": v.dv01,
    }


def _stack_cashflows(
    valuations: list[SwapValuation], attr: str, run_id: str, run_date, git_sha: str
) -> pd.DataFrame:
    frames = []
    for v in valuations:
        df = getattr(v, attr).copy()
        if df.empty:
            continue
        df.insert(0, "git_sha", git_sha)
        df.insert(0, "run_date", run_date)
        df.insert(0, "val_date", v.val_date)
        df.insert(0, "run_id", run_id)
        df.insert(4, "trade_id", v.trade_id)
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _curves_frame(
    curves: dict[str, ZeroCurve], run_id: str, val_date, run_date, git_sha: str
) -> pd.DataFrame:
    rows = []
    for name, c in curves.items():
        df = c.to_debug_frame()
        df.insert(0, "curve_name", name)
        rows.append(df)
    out = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    if not out.empty:
        out.insert(0, "git_sha", git_sha)
        out.insert(0, "run_date", run_date)
        out.insert(0, "val_date", val_date)
        out.insert(0, "run_id", run_id)
    return out


def write_portfolio_workbook(
    out_path: str | Path,
    valuations: list[SwapValuation],
    curves: dict[str, ZeroCurve],
    run_id: str,
    run_date,
    git_sha: str,
) -> None:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    val_date = valuations[0].val_date if valuations else None
    summary = pd.DataFrame([_summary_row(v, run_id, run_date, git_sha) for v in valuations])
    fl = _stack_cashflows(valuations, "floating_cf", run_id, run_date, git_sha)
    fx = _stack_cashflows(valuations, "fixed_cf", run_id, run_date, git_sha)
    curves_df = _curves_frame(curves, run_id, val_date, run_date, git_sha)
    with pd.ExcelWriter(out_path, engine="openpyxl") as w:
        summary.to_excel(w, sheet_name="Summary", index=False)
        fl.to_excel(w, sheet_name="FloatingCF", index=False)
        fx.to_excel(w, sheet_name="FixedCF", index=False)
        curves_df.to_excel(w, sheet_name="Curves", index=False)


def write_trade_debug_workbook(
    out_path: str | Path,
    swap,
    val_date,
    sofr: ZeroCurve,
    ff: ZeroCurve,
    fixings,
    grid_days: int | None = None,
) -> None:
    """Per-trade debug workbook: dump every intermediate frame as a separate tab.

    Tabs:
      SOFR_pillars / FF_pillars              -- raw curve parsing audit
      SOFR_df_grid / FF_df_grid              -- daily DFs over the trade's full
                                               horizon by default (val_date .. last
                                               cashflow); pass ``grid_days=N`` to
                                               clamp to a shorter front-end window.
      FixingsUsed                            -- historical fixings in the trade window
      FloatingFixings                        -- per-fixing rows BEFORE compounding (most useful for hand-checks)
      FloatingPeriods                        -- per-period historical product * projected product
      FloatingCF / FixedCF                   -- final cashflow tables (with discount factors)
    """
    from datetime import timedelta

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if grid_days is None:
        # Cover the trade's entire remaining horizon: last cashflow on either leg.
        last_dates: list = []
        if swap.fixed.schedule:
            last_dates.append(swap.fixed.schedule[-1].payment_date)
        if swap.floating.schedule:
            last_dates.append(swap.floating.schedule[-1].payment_date)
        grid_end = max(last_dates) if last_dates else val_date + timedelta(days=60)
        if grid_end <= val_date:
            grid_end = val_date + timedelta(days=60)  # matured trade fallback
    else:
        grid_end = val_date + timedelta(days=grid_days)
    with pd.ExcelWriter(out_path, engine="openpyxl") as w:
        sofr.to_debug_frame().to_excel(w, sheet_name="SOFR_pillars", index=False)
        ff.to_debug_frame().to_excel(w, sheet_name="FF_pillars", index=False)
        sofr.df_grid_debug(val_date, grid_end).to_excel(w, sheet_name="SOFR_df_grid", index=False)
        ff.df_grid_debug(val_date, grid_end).to_excel(w, sheet_name="FF_df_grid", index=False)
        fixings.to_debug_frame().to_excel(w, sheet_name="FixingsUsed", index=False)
        swap.floating.fixings_debug(val_date).to_excel(w, sheet_name="FloatingFixings", index=False)
        swap.floating.period_breakdown(val_date).to_excel(w, sheet_name="FloatingPeriods", index=False)
        swap.floating.cashflows(val_date, sofr).to_excel(w, sheet_name="FloatingCF", index=False)
        # Monthly-compounded view mirroring the fixed-leg cashflow granularity
        swap.floating.period_cashflows(val_date, sofr).to_excel(w, sheet_name="FloatingCF_byPeriod", index=False)
        swap.fixed.cashflows(val_date, sofr).to_excel(w, sheet_name="FixedCF", index=False)


def write_trade_detail_workbook(
    out_path: str | Path,
    v: SwapValuation,
    run_id: str,
    run_date,
    git_sha: str,
) -> None:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fl = v.floating_cf.copy()
    fx = v.fixed_cf.copy()
    fl_by_period = v.floating_cf_by_period.copy()
    for df in (fl, fx, fl_by_period):
        if not df.empty:
            df.insert(0, "git_sha", git_sha)
            df.insert(0, "run_date", run_date)
            df.insert(0, "val_date", v.val_date)
            df.insert(0, "run_id", run_id)
            df.insert(4, "trade_id", v.trade_id)
    with pd.ExcelWriter(out_path, engine="openpyxl") as w:
        fl.to_excel(w, sheet_name="Floating", index=False)
        fx.to_excel(w, sheet_name="Fixed", index=False)
        # Same monthly-compounded view as the debug workbook's
        # "FloatingCF_byPeriod" tab — available without enabling --debug.
        fl_by_period.to_excel(w, sheet_name="FloatingByPeriod", index=False)
