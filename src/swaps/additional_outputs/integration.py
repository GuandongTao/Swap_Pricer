"""Single-run integration: emit additional outputs from an in-memory priced run.

Called by ``Portfolio.run`` after the default IRS Valuation/Netting feeds are
written, reusing that run's already-priced valuations/swaps/market-data (no
repricing). Schedule-gated: each item runs only when due for the val_date.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from .base import RunContext, resolve_channel_dir, should_run
from .registry import REGISTRY

log = logging.getLogger("swaps.additional_outputs")


def emit_for_run(
    *,
    val_date: date,
    data_dir: Path,
    run_dir: Path,
    out_root: Path,
    trades: list,
    valuations: list,
    swaps_by_id: dict,
    md,
    new_deal_ids: frozenset[str] = frozenset(),
) -> dict[str, object]:
    """Produce all due additional outputs. Returns {item name -> [paths] | error}."""
    from .priced import PricedPortfolio, PricedTrade

    td_by_id = {td.trade_id: td for td in trades}
    pairs: list[PricedTrade] = []
    for v in valuations:
        if v.meta.get("matured"):
            continue
        swap = swaps_by_id.get(v.trade_id)
        td = td_by_id.get(v.trade_id)
        if swap is None or td is None:
            continue
        pairs.append(PricedTrade(td, v, swap))

    ctx = RunContext(
        val_date=val_date,
        data_dir=Path(data_dir),
        run_dir=Path(run_dir),
        out_root=Path(out_root),
        new_deal_ids=frozenset(new_deal_ids),
    )
    ctx.set_priced(PricedPortfolio(val_date=val_date, priced=pairs, md=md))

    results: dict[str, object] = {}
    for item in REGISTRY:
        if not should_run(item, val_date, ctx.new_deal_ids):
            continue
        dest = resolve_channel_dir(item.channel, ctx.run_dir)
        try:
            paths = item.produce(ctx, dest)
            results[item.name] = [str(p) for p in paths]
            for p in paths:
                log.info("additional output  %-24s -> %s", item.name, p)
        except Exception as e:  # noqa: BLE001 - report per-item, keep the run going
            results[item.name] = f"FAILED: {e}"
            log.exception("additional output  %-24s FAILED: %s", item.name, e)
    return results
