"""Additional-outputs CLI (separate from the default pricer feeds).

Produces schedule-driven additional output files. One command per val_date;
``--all`` forces every registered item regardless of its schedule. ``Once`` items
run only for swap ids named via ``--new-deal`` (repeatable).

Usage:
    # produce whichever additional outputs are due for this date
    python scripts/additional_outputs.py --val-date 2026-03-31

    # also produce the "Once" items for newly-added swap id(s)
    python scripts/additional_outputs.py --val-date 2026-03-31 --new-deal 20026619 --new-deal 20026620

    # force every additional output regardless of schedule
    python scripts/additional_outputs.py --val-date 2026-03-31 --all --new-deal 20026619

Exit codes:
    0  success      1  an item failed      2  CLI usage error
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# allow running without `pip install -e`
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from swaps.additional_outputs import (  # noqa: E402
    REGISTRY,
    RunContext,
    resolve_channel_dir,
    should_run,
)

log = logging.getLogger("additional_outputs")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--val-date", required=True, help="ISO date, e.g. 2026-03-31")
    p.add_argument("--data-dir", default=str(ROOT / "data"), help="Base data directory")
    p.add_argument("--out-dir", default=str(ROOT / "output"), help="Output dir (SFTP channel root)")
    p.add_argument("--new-deal", action="append", default=[], metavar="SWAP_ID",
                   help="Newly-added swap id to trigger 'Once' items (repeatable)")
    p.add_argument("--all", action="store_true", help="Force all items regardless of schedule")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    try:
        val_date = datetime.strptime(args.val_date, "%Y-%m-%d").date()
    except ValueError as e:
        log.error("Bad --val-date: %s", e)
        return 2

    new_deal_ids = frozenset(str(x).strip() for x in args.new_deal if str(x).strip())
    out_dir = Path(args.out_dir)
    ctx = RunContext(
        val_date=val_date,
        data_dir=Path(args.data_dir),
        run_dir=out_dir,
        out_root=out_dir,
        new_deal_ids=new_deal_ids,
    )

    produced = 0
    failed = 0
    for item in REGISTRY:
        if not should_run(item, val_date, new_deal_ids, force=args.all):
            log.info("skip   %-26s (%s)", item.name, item.frequency.value)
            continue
        dest = resolve_channel_dir(item.channel, ctx.run_dir)
        try:
            paths = item.produce(ctx, dest)
        except Exception as e:  # noqa: BLE001 - report per-item, keep going
            failed += 1
            log.exception("FAIL   %-26s: %s", item.name, e)
            continue
        produced += 1
        if not paths:
            log.info("ok     %-26s (no files for this input)", item.name)
        for pth in paths:
            log.info("write  %-26s -> %s", item.name, pth)

    log.info("done: %d item(s) produced, %d failed", produced, failed)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
