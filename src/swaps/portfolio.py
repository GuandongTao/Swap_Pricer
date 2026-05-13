"""Portfolio runner: orchestrate loaders -> pricer -> writers."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

_log = logging.getLogger(__name__)


@contextmanager
def _timed(timings: dict, label: str):
    t0 = time.perf_counter()
    try:
        yield
    finally:
        timings[label] = time.perf_counter() - t0

from .curve import ZeroCurve
from .io_excel import write_portfolio_workbook, write_trade_debug_workbook, write_trade_detail_workbook
from .io_parquet import write_parquet_outputs
from .loaders.base import CurveLoader, FixingLoader, TradeLoader
from .manifest import RunManifest
from .market_data import MarketData
from .pricer import SwapPricer, SwapValuation
from .trade_builder import build_swap


class Portfolio:
    def __init__(
        self,
        curve_loader: CurveLoader,
        fixing_loader: FixingLoader,
        trade_loader: TradeLoader,
        pricer: SwapPricer | None = None,
    ) -> None:
        self.curve_loader = curve_loader
        self.fixing_loader = fixing_loader
        self.trade_loader = trade_loader
        self.pricer = pricer or SwapPricer()

    def run(
        self,
        val_date: date,
        out_dir: str | Path = "output",
        write_detail: bool = True,
        write_parquet: bool = True,
        write_debug: bool = False,
    ) -> tuple[list[SwapValuation], RunManifest]:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        manifest = RunManifest.new(val_date)
        timings: dict[str, float] = {}
        per_trade_timings: dict[str, float] = {}

        with _timed(timings, "load_curves"):
            sofr = self.curve_loader.load(val_date, "SOFR")
            ff = self.curve_loader.load(val_date, "FEDFUNDS")
        with _timed(timings, "load_fixings"):
            fixings = self.fixing_loader.load("FEDFUNDS")
        with _timed(timings, "load_trades"):
            trades = self.trade_loader.load_all()
        md = MarketData(val_date=val_date, discount_curve=sofr, projection_curve=ff, fixings=fixings)
        manifest.trade_count = len(trades)

        valuations: list[SwapValuation] = []
        swaps_by_id: dict[str, "Swap"] = {}
        with _timed(timings, "price_all"):
            for td in trades:
                t0 = time.perf_counter()
                try:
                    swap = build_swap(td, ff, fixings)
                    v = self.pricer.price(swap, md)
                    valuations.append(v)
                    swaps_by_id[v.trade_id] = swap
                except Exception as e:
                    manifest.errors.append(f"{td.trade_id}: {e}")
                per_trade_timings[td.trade_id] = time.perf_counter() - t0

        # Excel and Parquet writers need a tz-naive datetime (UTC seconds).
        run_date = manifest.run_date.replace(tzinfo=None)
        portfolio_path = out_dir / f"portfolio_{val_date.isoformat()}.xlsx"
        with _timed(timings, "write_portfolio_xlsx"):
            write_portfolio_workbook(
                portfolio_path, valuations, {"SOFR": sofr, "FEDFUNDS": ff},
                manifest.run_id, run_date, manifest.git_sha,
            )
        manifest.outputs["portfolio_xlsx"] = str(portfolio_path)

        if write_detail:
            with _timed(timings, "write_detail_xlsx"):
                detail_dir = out_dir / "detail"
                for v in valuations:
                    p = detail_dir / f"{v.trade_id}.xlsx"
                    write_trade_detail_workbook(p, v, manifest.run_id, run_date, manifest.git_sha)
                manifest.outputs["detail_dir"] = str(detail_dir)

        if write_debug:
            with _timed(timings, "write_debug_xlsx"):
                debug_dir = out_dir / "debug"
                for v in valuations:
                    p = debug_dir / f"{v.trade_id}_debug.xlsx"
                    write_trade_debug_workbook(p, swaps_by_id[v.trade_id], val_date, sofr, ff, fixings)
                manifest.outputs["debug_dir"] = str(debug_dir)

        if write_parquet:
            with _timed(timings, "write_parquet"):
                pq_dir = out_dir / "parquet" / val_date.isoformat()
                paths = write_parquet_outputs(
                    pq_dir, valuations, {"SOFR": sofr, "FEDFUNDS": ff},
                    manifest.run_id, run_date, manifest.git_sha,
                )
                manifest.outputs["parquet"] = {k: str(p) for k, p in paths.items()}

        manifest.finished_at = datetime.now(timezone.utc)
        manifest.status = "ok" if not manifest.errors else "partial"
        timings["total"] = (manifest.finished_at - manifest.started_at).total_seconds()
        manifest.timings = timings
        manifest.per_trade_timings = per_trade_timings

        manifest_path = out_dir / f"manifest_{val_date.isoformat()}.json"
        manifest.write(manifest_path)
        manifest.outputs["manifest"] = str(manifest_path)

        # Log a concise performance summary.
        _log.info(
            "Timing: total=%.2fs  load_curves=%.2fs  load_fixings=%.2fs  load_trades=%.2fs  "
            "price_all=%.2fs (%.0fms/trade avg)  write_xlsx=%.2fs  write_parquet=%.2fs",
            timings["total"],
            timings.get("load_curves", 0.0),
            timings.get("load_fixings", 0.0),
            timings.get("load_trades", 0.0),
            timings.get("price_all", 0.0),
            (timings.get("price_all", 0.0) / max(len(valuations), 1)) * 1000.0,
            timings.get("write_portfolio_xlsx", 0.0) + timings.get("write_detail_xlsx", 0.0)
            + timings.get("write_debug_xlsx", 0.0),
            timings.get("write_parquet", 0.0),
        )
        if per_trade_timings:
            per = " ".join(f"{tid}={t*1000:.0f}ms" for tid, t in per_trade_timings.items())
            _log.info("Per-trade pricing: %s", per)

        return valuations, manifest
