"""Batch runner: price several valuation dates in parallel.

Each date is priced by an independent ``Portfolio.run`` call, which already
writes a self-contained ``<out_dir>/run_<val_date>/`` folder. This module just
fans those runs out across processes (pricing is CPU-bound) and collects a
light-weight summary -- the heavy per-trade DataFrames stay on disk, never
crossing the process boundary.

Each date keeps its own normal daily summary inside ``run_<val_date>/``. The
batch additionally writes one overarching ``batch_<UTCstamp>.log`` (+ ``.json``)
at the ``out_dir`` root, outside all the day folders, summarizing every date.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

_log = logging.getLogger(__name__)


@dataclass
class BatchResult:
    val_date: date
    status: str  # "ok" | "partial" | "error"
    run_dir: str | None
    manifest_path: str | None
    trade_count: int
    errors: list[str]
    exception: str | None = None


def _run_one(
    val_date: date,
    data_dir: str,
    out_dir: str,
    fixing_file: str,
    write_detail: bool,
    write_parquet: bool,
    write_debug: bool,
    pillar_dates: bool = False,
    pillar_dates_df: bool = False,
    verbose: bool = False,
    entity_rc_path: str | None = None,
    netting_db_path: str | None = None,
) -> BatchResult:
    """Process-pool worker. Builds loaders *inside* the worker so nothing
    unpicklable (curves, loader objects) crosses the process boundary."""
    # Imports are inside the worker so the child process sets them up cleanly.
    import logging as _logging
    import sys as _sys

    from swaps.io_prod import load_entity_rc
    from swaps.netting_db import load_netting_db
    from swaps.loaders import CombinedTradeLoader
    from swaps.loaders.csv_trades import CsvTradeLoader
    from swaps.loaders.dated import DatedCurveLoader, DatedDFCurveLoader
    from swaps.loaders.excel import ExcelCurveLoader, ExcelFixingLoader
    from swaps.loaders.yaml_trades import YamlTradeLoader
    from swaps.portfolio import Portfolio

    # Configure logging inside the worker process so the SAME detailed
    # per-trade progress you get from a single-date run is emitted here too
    # (child processes don't inherit the parent's logging config). Lines are
    # prefixed with the val_date so parallel workers stay attributable.
    _logging.basicConfig(
        level=_logging.INFO if verbose else _logging.ERROR, stream=_sys.stdout,
        format=f"%(asctime)s %(levelname)s [val={val_date}] %(message)s",
    )
    _wlog = _logging.getLogger(f"batch.{val_date}")
    _wlog.info("===== val_date %s : run START =====", val_date)

    dd = Path(data_dir)
    try:
        if pillar_dates_df:
            curve_loader = DatedDFCurveLoader(dd / "curves")
        elif pillar_dates:
            curve_loader = DatedCurveLoader(dd / "curves")
        else:
            curve_loader = ExcelCurveLoader(dd / "curves")
        pf = Portfolio(
            curve_loader,
            ExcelFixingLoader(dd / "fixings" / fixing_file),
            CombinedTradeLoader(
                YamlTradeLoader(dd / "trades"),
                CsvTradeLoader(dd / "trades"),
            ),
        )
        entity_rc = load_entity_rc(entity_rc_path) if entity_rc_path else {}
        netting_db = None
        if netting_db_path and Path(netting_db_path).exists():
            netting_db = load_netting_db(netting_db_path)
        _, manifest = pf.run(
            val_date,
            out_dir=out_dir,
            write_prod=True,
            write_portfolio_xlsx=write_debug,
            write_detail=write_detail,
            write_parquet=write_parquet,
            write_debug=write_debug,
            entity_rc=entity_rc,
            netting_db=netting_db,
        )
        _wlog.info("===== val_date %s : run DONE (status=%s) =====",
                   val_date, manifest.status)
        return BatchResult(
            val_date=val_date,
            status=manifest.status,
            run_dir=manifest.outputs.get("run_dir"),
            manifest_path=manifest.outputs.get("manifest"),
            trade_count=manifest.trade_count,
            errors=list(manifest.errors),
        )
    except FileNotFoundError as e:
        # No zero-rate curve for this date (typically a weekend / holiday
        # with no published curve). This is expected -> WARNING, not error,
        # and it must NOT fail the batch exit code.
        _wlog.warning("val_date %s SKIPPED: no curve available (%s)", val_date, e)
        return BatchResult(
            val_date=val_date,
            status="skipped",
            run_dir=None,
            manifest_path=None,
            trade_count=0,
            errors=[],
            exception=f"no curve for {val_date}: {e}",
        )
    except Exception as e:  # one bad date must not sink the whole batch
        _wlog.error("val_date %s ERROR: %s: %s", val_date, type(e).__name__, e)
        return BatchResult(
            val_date=val_date,
            status="error",
            run_dir=None,
            manifest_path=None,
            trade_count=0,
            errors=[],
            exception=f"{type(e).__name__}: {e}",
        )


def run_batch(
    val_dates: list[date],
    *,
    data_dir: str | Path,
    out_dir: str | Path = "output",
    fixing_file: str = "fixing_cail_USD-FEDFUNDS-ON.csv",
    max_workers: int | None = None,
    write_detail: bool = False,
    write_parquet: bool = False,
    write_debug: bool = False,
    pillar_dates: bool = False,
    pillar_dates_df: bool = False,
    verbose: bool = False,
    entity_rc_path: str | Path | None = None,
    netting_db_path: str | Path | None = None,
) -> list[BatchResult]:
    """Price ``val_dates`` in parallel. Returns one ``BatchResult`` per date,
    ordered by ``val_date``. Each date's outputs land in
    ``<out_dir>/run_<val_date>/``.
    """
    dates = sorted(set(val_dates))
    if not dates:
        raise ValueError("run_batch requires at least one valuation date")
    data_dir = str(Path(data_dir))
    out_dir = str(Path(out_dir))
    entity_rc_path_str = str(Path(entity_rc_path)) if entity_rc_path else None
    netting_db_path_str = str(Path(netting_db_path)) if netting_db_path else None
    results: list[BatchResult] = []

    _log.info(
        "Batch: %d valuation date(s) %s .. %s, max_workers=%s",
        len(dates), dates[0], dates[-1], max_workers or "auto",
    )
    with ProcessPoolExecutor(max_workers=max_workers) as ex:
        futs = {
            ex.submit(
                _run_one, d, data_dir, out_dir, fixing_file,
                write_detail, write_parquet, write_debug,
                pillar_dates, pillar_dates_df, verbose,
                entity_rc_path_str, netting_db_path_str,
            ): d
            for d in dates
        }
        for fut in as_completed(futs):
            r = fut.result()
            if r.status == "error":
                _log.error("  %s  ERROR: %s", r.val_date, r.exception)
            elif r.status == "skipped":
                _log.warning("  %s  SKIPPED (no curve): %s", r.val_date, r.exception)
            else:
                _log.info(
                    "  %s  status=%s trades=%d -> %s",
                    r.val_date, r.status, r.trade_count, r.run_dir,
                )
            results.append(r)

    results.sort(key=lambda r: r.val_date)

    # Each date still writes its own normal daily summary inside run_<date>/.
    # In addition, write ONE overarching batch log at the out_dir root (a
    # sibling of the run_<date>/ folders, not inside any of them) so the whole
    # batch is auditable from a single file.
    ts = datetime.now(timezone.utc)
    stamp = ts.strftime("%Y%m%dT%H%M%SZ")
    n_ok = sum(1 for r in results if r.status == "ok")
    n_partial = sum(1 for r in results if r.status == "partial")
    n_err = sum(1 for r in results if r.status == "error")
    n_skip = sum(1 for r in results if r.status == "skipped")

    base = Path(out_dir)
    base.mkdir(parents=True, exist_ok=True)
    log_path = base / f"batch_{stamp}.log"
    lines = [
        f"Batch run {ts.isoformat()}",
        f"Dates: {len(results)} ({dates[0]} .. {dates[-1]})  "
        f"ok={n_ok} partial={n_partial} error={n_err} skipped(no-curve)={n_skip}",
        "",
    ]
    for r in results:
        lines.append(
            f"  {r.val_date}  status={r.status:<7} trades={r.trade_count:<4} "
            f"-> {r.run_dir or '(no output)'}"
        )
        if r.exception:
            lines.append(f"      exception: {r.exception}")
        for e in r.errors:
            lines.append(f"      error: {e}")
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    json_path = base / f"batch_{stamp}.json"
    json_path.write_text(
        json.dumps(
            {
                "run_at": ts.isoformat(),
                "totals": {"ok": n_ok, "partial": n_partial, "error": n_err,
                           "skipped_no_curve": n_skip, "total": len(results)},
                "dates": [
                    {
                        "val_date": r.val_date.isoformat(),
                        "status": r.status,
                        "trade_count": r.trade_count,
                        "run_dir": r.run_dir,
                        "manifest": r.manifest_path,
                        "errors": r.errors,
                        "exception": r.exception,
                    }
                    for r in results
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _log.info(
        "Batch summary: %d ok, %d partial, %d error, %d skipped(no-curve) -> %s",
        n_ok, n_partial, n_err, n_skip, log_path,
    )
    return results
