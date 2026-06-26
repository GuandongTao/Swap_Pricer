"""Portfolio runner: orchestrate loaders -> pricer -> writers."""

from __future__ import annotations

import logging
import re
import time
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from .calendar_us import month_end_curve_date
from .curve import ZeroCurve
from .debt import (
    debt_discount_curve, debt_summary_filename, debt_summary_row,
    resolve_hedged_debt_mtm, value_debt, write_debt_summary_csv,
)
from .io_excel import write_portfolio_workbook, write_trade_debug_workbook, write_trade_detail_workbook
from .io_parquet import write_parquet_outputs
from .io_prod import prod_filename, write_prod_csv
from .io_prod_netting import netting_filename, write_netting_csv
from .loaders.base import CurveLoader, FixingLoader, TradeLoader
from .manifest import RunManifest
from .market_data import MarketData
from .netting_db import NettingRow
from .pricer import SwapPricer, SwapValuation
from .trade_builder import build_debt_leg, build_swap

_log = logging.getLogger(__name__)

TRADE_ID_PREFIX = "AMEX_DAILY_IRS"

VERSION_WIDTH = 5


def _fmt_version(n: int) -> str:
    """Zero-pad a submission sequence number to the spec's 5-digit width."""
    return f"{n:0{VERSION_WIDTH}d}"


def _next_version(base_out: Path, val_date: date, folder_suffix: str) -> str:
    """Auto-detect the next submission version for this ``(val_date, source)``.

    Scans ``base_out`` for prior run folders of the *same* valuation date and the
    *same* data source (the ``folder_suffix``, e.g. ``" BBG"``), parses their
    trailing ``_ver_<NNNNN>`` segment, and returns ``max + 1`` (or ``00001`` if
    none exist). The ``_ver_`` anchor sits immediately after the run-date (and
    after the source suffix), so a non-BBG scan never matches a ``" BBG"`` folder
    and vice-versa -- the two lineages version independently.
    """
    pat = re.compile(
        rf"^valdate_{re.escape(val_date.isoformat())}"
        rf"_rundate_\d{{4}}-\d{{2}}-\d{{2}}{re.escape(folder_suffix)}"
        rf"_ver_(\d+)$"
    )
    highest = 0
    if base_out.exists():
        for child in base_out.iterdir():
            if not child.is_dir():
                continue
            m = pat.match(child.name)
            if m:
                highest = max(highest, int(m.group(1)))
    return _fmt_version(highest + 1)


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
def _timed(timings: dict[str, float], label: str):
    """Context manager that records elapsed seconds for ``label`` into ``timings``."""
    t0 = time.perf_counter()
    try:
        yield
    finally:
        timings[label] = time.perf_counter() - t0


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
        write_detail: bool = False,
        write_parquet: bool = False,
        write_debug: bool = False,
        write_portfolio_xlsx: bool = False,
        write_prod: bool = True,
        write_debt_summary: bool = False,
        entity_rc: dict[str, str] | None = None,
        netting_db: dict[str, NettingRow] | None = None,
        folder_suffix: str = "",
        version: str | int | None = None,
        data_dir: str | Path | None = None,
        additional_outputs: bool = True,
        new_deal_ids: frozenset[str] = frozenset(),
    ) -> tuple[list[SwapValuation], RunManifest]:
        manifest = RunManifest.new(val_date)

        # Every run is self-contained in its own folder, named with BOTH the
        # valuation date and the run (execution) date so reruns for different
        # business days are kept distinct and a same-day rerun is idempotent:
        #   <out_dir>/valdate_<val_date>_rundate_<run_date>/
        #       {portfolio_*.xlsx, detail/, debug/, parquet/, manifest_*.json}
        base_out = Path(out_dir)
        # folder_suffix marks the data source in the folder name (e.g. " BBG"
        # when curves came from --pillar-dates-df / Bloomberg DF files).
        #
        # Submission version: an explicit override (--version) wins; otherwise
        # auto-increment past any prior run for this same (val_date, source).
        # The same 5-digit stamp drives the folder name AND the feed filename /
        # header so the file's version always follows its directory.
        if version is None:
            version_stamp = _next_version(base_out, val_date, folder_suffix)
        else:
            version_stamp = _fmt_version(int(version))
        manifest.version = version_stamp
        run_folder = (
            f"valdate_{val_date.isoformat()}"
            f"_rundate_{manifest.run_date:%Y-%m-%d}"
            f"{folder_suffix}"
            f"_ver_{version_stamp}"
        )
        out_dir = base_out / run_folder
        out_dir.mkdir(parents=True, exist_ok=True)
        _log.info("Run folder: %s", out_dir)
        timings: dict[str, float] = {}
        per_trade_timings: dict[str, float] = {}

        run_start = time.perf_counter()
        # Month-end on a weekend/holiday: no published market data for val_date,
        # so the curve loaders fall back to the previous business day's file
        # (curve stays anchored at val_date). Announce it on stdout + manifest.
        fb_curve_date = month_end_curve_date(val_date)
        if fb_curve_date is not None:
            msg = (
                f"Month-end valuation {val_date} falls on a non-business day; "
                f"using previous-close market data from {fb_curve_date}."
            )
            _log.warning(msg)
            manifest.warnings.append(msg)
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

        # Hedged debt for col AW (only when writing the prod feed) is now VALUED
        # in-process per LH trade (swaps.debt) from each trade's inline debt_*
        # block, then written to Debt_Summary_<val_date>.csv as a run artifact.
        # Collected in the pricing loop below.
        debt_summary_rows: list[dict[str, object]] = []

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
                debt_status: str | None = None   # "priced" | "skipped" (LH/SC)
                debt_dt = 0.0
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
                        for w in swap.meta.get("convention_warnings", []):
                            _log.warning(w)
                            manifest.warnings.append(w)
                        v = self.pricer.price(swap, md)
                        if write_prod:
                            # Per-trade hard error if hedge is blank/unknown or an
                            # LH trade's debt block is missing/unpriceable.
                            debt_mtm_value: float | None = None
                            if (td.hedge or "").strip().upper() == "LH":
                                dt0 = time.perf_counter()
                                # Debt is discounted on Fed Funds (not SOFR).
                                dv = value_debt(td, ff, val_date)
                                debt_dt = time.perf_counter() - dt0
                                debt_mtm_value = dv["clean"] + td.debt_notional
                                debt_summary_rows.append(
                                    debt_summary_row(td, dv["clean"], dv["accrued"], dv["dirty"])
                                )
                                debt_status = "priced"
                            else:
                                debt_status = "skipped"
                            v.meta["hedged_debt_mtm"] = resolve_hedged_debt_mtm(
                                td.trade_id, td.hedge, td.debt_deal_number,
                                v.clean, debt_mtm_value,
                            )
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
                # Hedged-debt (loan) pricing status, mirroring the IRS line above.
                if debt_status == "priced":
                    _log.info(
                        "        debt %s  priced in %5.2fs (deal %s)",
                        td.trade_id, debt_dt, td.debt_deal_number,
                    )
                elif debt_status == "skipped":
                    _log.info("        debt %s  skipped (SC -- no debt to value)", td.trade_id)

        # Excel and Parquet writers need a tz-naive datetime (UTC seconds).
        run_date = manifest.run_date.replace(tzinfo=None)

        # Trade-defs keyed by their qualified id so the prod writer can pull
        # per-trade reference data (counterparty, deal date, etc.) that isn't
        # carried on SwapValuation.
        trades_by_id = {td.trade_id: td for td in trades}

        if write_prod:
            prod_path = out_dir / prod_filename(val_date, version_stamp)
            _log.info("Writing prod CSV -> %s", prod_path)
            with _timed(timings, "write_prod_csv"):
                write_prod_csv(
                    prod_path, trades_by_id, valuations, val_date,
                    entity_rc=entity_rc, netting_db=netting_db,
                    version=version_stamp,
                )
            manifest.outputs["prod_csv"] = str(prod_path)
            # Debt_Summary artifact: the computed Clean/Accrued/Dirty for every
            # LH-hedged debt that fed col AW (empty file -- title + headers --
            # when no LH trades). Gated behind --debug-loan / --debug-full; the
            # debt is still valued for col AW regardless. Replaces the
            # externally-produced Deal_Summary.
            if write_debt_summary:
                debt_summary_path = out_dir / debt_summary_filename(val_date)
                _log.info("Writing Debt Summary -> %s (%d debts)", debt_summary_path, len(debt_summary_rows))
                with _timed(timings, "write_debt_summary"):
                    write_debt_summary_csv(debt_summary_path, debt_summary_rows)
                manifest.outputs["debt_summary_csv"] = str(debt_summary_path)
            # IRS Netting feed: same gating as IRS Valuation. Requires both the
            # netting DB (per-netting-id fields) and the entity_rc lookup
            # (CCID RC). If either is missing, skip with a warning rather than
            # failing the whole run -- the valuation feed is the primary
            # deliverable.
            if netting_db is not None and entity_rc:
                netting_path = out_dir / netting_filename(val_date, version_stamp)
                _log.info("Writing netting CSV -> %s", netting_path)
                with _timed(timings, "write_netting_csv"):
                    write_netting_csv(
                        netting_path, trades_by_id, valuations, val_date,
                        netting_db=netting_db, entity_rc=entity_rc,
                        version=version_stamp,
                    )
                manifest.outputs["netting_csv"] = str(netting_path)
            else:
                msg = (
                    "IRS Netting CSV skipped: "
                    f"netting_db={'present' if netting_db else 'missing'}, "
                    f"entity_rc={'present' if entity_rc else 'missing'}."
                )
                _log.warning(msg)
                manifest.warnings.append(msg)

        if write_portfolio_xlsx:
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
                    # LH trades: include the hedged bond's cashflows/accrued as
                    # extra tabs in the same workbook.
                    td_dbg = trades_by_id.get(v.trade_id)
                    debt_leg = (
                        build_debt_leg(td_dbg)
                        if td_dbg is not None and (td_dbg.hedge or "").strip().upper() == "LH"
                        else None
                    )
                    debt_curve = debt_discount_curve(td_dbg, ff) if debt_leg is not None else None
                    write_trade_debug_workbook(
                        p, swaps_by_id[v.trade_id], val_date, sofr, ff, fixings,
                        debt_leg=debt_leg, debt_curve=debt_curve,
                    )
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

        # Additional outputs (Treasury, Payment Report, Day 1, ...): generated in
        # this SAME run from the in-memory priced data -- schedule-gated, no
        # repricing. SFTP items land in this run folder; email items in
        # <run folder>/email. Best-effort: a failure here never fails the run.
        if additional_outputs and data_dir is not None:
            try:
                from .additional_outputs.integration import emit_for_run

                with _timed(timings, "additional_outputs"):
                    res = emit_for_run(
                        val_date=val_date,
                        data_dir=Path(data_dir),
                        run_dir=out_dir,
                        out_root=base_out,
                        trades=trades,
                        valuations=valuations,
                        swaps_by_id=swaps_by_id,
                        md=md,
                        new_deal_ids=new_deal_ids,
                    )
                if res:
                    manifest.outputs["additional_outputs"] = res
            except Exception:  # noqa: BLE001 - never let extras fail the core run
                _log.exception("Additional outputs failed (core run unaffected)")

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
