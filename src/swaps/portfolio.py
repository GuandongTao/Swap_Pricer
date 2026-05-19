"""Portfolio runner: orchestrate loaders -> pricer -> writers."""

from __future__ import annotations

import logging
import re
import time
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

_log = logging.getLogger(__name__)

TRADE_ID_PREFIX = "AMEX_DAILY_IRS"


def _qualify_amex_id(raw: str, val_date: date) -> tuple[str, str]:
    """Reconstruct the full trade id from the trailing unique id number.

    Returns ``(full_id, short_id)`` where
    ``full_id = AMEX_DAILY_IRS_<YYYYMMDD>_<short_id>``. A legacy fully-qualified
    id pasted into the input is tolerated: its trailing token is taken as the
    short id so re-qualification is idempotent.
    """
    s = str(raw).strip()
    if s.upper().startswith(TRADE_ID_PREFIX):
        s = re.split(r"[-_]", s)[-1]
    return f"{TRADE_ID_PREFIX}_{val_date:%Y%m%d}_{s}", s


@contextmanager
def _timed(timings: dict, label: str):
    t0 = time.perf_counter()
    try:
        yield
    finally:
        timings[label] = time.perf_counter() - t0

import pandas as pd

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
        manifest = RunManifest.new(val_date)

        # Every run is self-contained in its own folder, named with BOTH the
        # valuation date and the run (execution) date so reruns for different
        # business days are kept distinct and a same-day rerun is idempotent:
        #   <out_dir>/valdate_<val_date>_rundate_<run_date>/
        #       {portfolio_*.xlsx, detail/, debug/, parquet/, manifest_*.json}
        base_out = Path(out_dir)
        run_folder = (
            f"valdate_{val_date.isoformat()}"
            f"_rundate_{manifest.run_date:%Y-%m-%d}"
        )
        out_dir = base_out / run_folder
        out_dir.mkdir(parents=True, exist_ok=True)
        _log.info("Run folder: %s", out_dir)
        timings: dict[str, float] = {}
        per_trade_timings: dict[str, float] = {}

        run_start = time.perf_counter()
        _log.info("Loading curves and fixings for val_date=%s ...", val_date)
        with _timed(timings, "load_curves"):
            sofr = self.curve_loader.load(val_date, "SOFR")
            ff = self.curve_loader.load(val_date, "FEDFUNDS")
        with _timed(timings, "load_fixings"):
            fixings = self.fixing_loader.load("FEDFUNDS")
        with _timed(timings, "load_trades"):
            trades = self.trade_loader.load_all()
        # Reconstruct AMEX daily IRS ids now that the valuation date is known.
        # Trades from other loaders (e.g. yaml debug fixtures) keep their id.
        for td in trades:
            if td.meta.get("_id_scheme") == "amex_daily_irs":
                full_id, short_id = _qualify_amex_id(td.meta.get("id", td.trade_id), val_date)
                td.trade_id = full_id
                td.meta = {**td.meta, "id": short_id}
        md = MarketData(val_date=val_date, discount_curve=sofr, projection_curve=ff, fixings=fixings)
        manifest.trade_count = len(trades)
        _log.info(
            "Loaded %d pillars SOFR / %d pillars FF / %d fixings / %d trades  (%.2fs)",
            len(sofr.pillars), len(ff.pillars), len(fixings), len(trades),
            time.perf_counter() - run_start,
        )

        valuations: list[SwapValuation] = []
        swaps_by_id: dict[str, "Swap"] = {}
        n_total = len(trades)
        priced_count = 0
        failed_count = 0
        with _timed(timings, "price_all"):
            for i, td in enumerate(trades, start=1):
                t0 = time.perf_counter()
                ok = False
                matured = False
                err: str | None = None
                try:
                    if td.maturity_date < val_date:
                        matured = True
                        msg = (
                            f"{td.trade_id}: matured (maturity {td.maturity_date} < val_date {val_date}); "
                            "valuation set to 0"
                        )
                        manifest.warnings.append(msg)
                        v = SwapValuation(
                            trade_id=td.trade_id,
                            val_date=val_date,
                            clean=0.0, dirty=0.0, accrued=0.0, dv01=0.0,
                            pv_fixed=0.0, pv_floating=0.0,
                            par_rate=float("nan"), rate_diff_bp=float("nan"),
                            fixed_cf=pd.DataFrame(),
                            floating_cf=pd.DataFrame(),
                            meta={
                                "matured": True,
                                "id": td.meta.get("id"),
                                "notional": td.notional,
                                "fixed_rate": td.fixed_rate,
                                "start_date": td.start_date,
                                "maturity_date": td.maturity_date,
                            },
                        )
                        valuations.append(v)
                        ok = True
                    else:
                        swap = build_swap(td, ff, fixings)
                        v = self.pricer.price(swap, md)
                        valuations.append(v)
                        swaps_by_id[v.trade_id] = swap
                        ok = True
                except Exception as e:
                    err = str(e).splitlines()[0][:120]
                    manifest.errors.append(f"{td.trade_id}: {e}")
                dt = time.perf_counter() - t0
                per_trade_timings[td.trade_id] = dt
                elapsed = time.perf_counter() - run_start
                if matured:
                    priced_count += 1
                    _log.warning(
                        "[%d/%d] %s  MATURED (maturity %s < val_date %s) -> value 0   "
                        "priced=%d failed=%d  elapsed %5.1fs",
                        i, n_total, td.trade_id, td.maturity_date, val_date,
                        priced_count, failed_count, elapsed,
                    )
                elif ok:
                    priced_count += 1
                    _log.info(
                        "[%d/%d] %s  priced in %5.2fs   priced=%d failed=%d  elapsed %5.1fs",
                        i, n_total, td.trade_id, dt, priced_count, failed_count, elapsed,
                    )
                else:
                    failed_count += 1
                    _log.warning(
                        "[%d/%d] %s  FAILED: %s   priced=%d failed=%d  elapsed %5.1fs",
                        i, n_total, td.trade_id, err, priced_count, failed_count, elapsed,
                    )

        # Excel and Parquet writers need a tz-naive datetime (UTC seconds).
        run_date = manifest.run_date.replace(tzinfo=None)
        portfolio_path = out_dir / f"portfolio_{val_date.isoformat()}.xlsx"
        _log.info("Writing portfolio workbook -> %s", portfolio_path)
        with _timed(timings, "write_portfolio_xlsx"):
            write_portfolio_workbook(
                portfolio_path, valuations, {"SOFR": sofr, "FEDFUNDS": ff},
                manifest.run_id, run_date, manifest.git_sha,
            )
        manifest.outputs["portfolio_xlsx"] = str(portfolio_path)

        if write_detail:
            _log.info("Writing %d detail workbooks ...", len(valuations))
            with _timed(timings, "write_detail_xlsx"):
                detail_dir = out_dir / "detail"
                for i, v in enumerate(valuations, start=1):
                    if v.meta.get("matured"):
                        _log.info("  detail [%d/%d] %s skipped (matured)", i, len(valuations), v.trade_id)
                        continue
                    t0 = time.perf_counter()
                    p = detail_dir / f"{v.trade_id}.xlsx"
                    write_trade_detail_workbook(p, v, manifest.run_id, run_date, manifest.git_sha)
                    _log.info("  detail [%d/%d] %s.xlsx (%.2fs)", i, len(valuations), v.trade_id,
                              time.perf_counter() - t0)
                manifest.outputs["detail_dir"] = str(detail_dir)

        if write_debug:
            _log.info("Writing %d debug workbooks ...", len(valuations))
            with _timed(timings, "write_debug_xlsx"):
                debug_dir = out_dir / "debug"
                for i, v in enumerate(valuations, start=1):
                    if v.meta.get("matured") or v.trade_id not in swaps_by_id:
                        _log.info("  debug  [%d/%d] %s skipped (matured)", i, len(valuations), v.trade_id)
                        continue
                    t0 = time.perf_counter()
                    p = debug_dir / f"{v.trade_id}_debug.xlsx"
                    write_trade_debug_workbook(p, swaps_by_id[v.trade_id], val_date, sofr, ff, fixings)
                    _log.info("  debug  [%d/%d] %s_debug.xlsx (%.2fs)", i, len(valuations), v.trade_id,
                              time.perf_counter() - t0)
                manifest.outputs["debug_dir"] = str(debug_dir)

        if write_parquet:
            _log.info("Writing parquet outputs ...")
            with _timed(timings, "write_parquet"):
                pq_dir = out_dir / "parquet"
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

        manifest.outputs["run_dir"] = str(out_dir)
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
