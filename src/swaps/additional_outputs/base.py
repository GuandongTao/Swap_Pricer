"""Additional-outputs framework: frequencies, channels, run context, item record.

Separate from the default pricer feeds. An *additional output* is a file (or set
of files) produced on a schedule (``Frequency``) and routed to a destination
(``Channel``). The default IRS Valuation / Netting feeds are NOT managed here and
are untouched by this package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from ..calendar_us import is_month_end

if TYPE_CHECKING:
    from .priced import PricedPortfolio

_QUARTER_END_MONTHS = {3, 6, 9, 12}


class Frequency(str, Enum):
    """When an item is produced. Month-end = last *calendar* day of the month."""

    DAILY = "daily"
    MONTH_END = "month-end"
    QUARTER_END = "quarter-end"
    ONCE = "once"  # not calendar-driven; gated by --new-deal-<id>


class Channel(str, Enum):
    """Where an item is written. SFTP -> output tree; EMAIL -> ``email/`` parallel."""

    SFTP = "sftp"
    EMAIL = "email"


@dataclass
class RunContext:
    """Inputs + lazily-priced portfolio shared across items in one run.

    * ``run_dir`` -- this run's dated output folder (SFTP base; email = run_dir/email).
    * ``out_root`` -- the base ``output/`` dir, for cross-run lookups (e.g. the
      Treasury report's previous-month file, which lives in a different run folder).
    """

    val_date: date
    data_dir: Path
    run_dir: Path
    out_root: Path
    new_deal_ids: frozenset[str] = frozenset()
    _priced: "PricedPortfolio | None" = field(default=None, init=False, repr=False, compare=False)

    def priced(self) -> "PricedPortfolio":
        """Price the portfolio once (cached). Read-only reuse of the pricer.

        In the integrated single-run path the priced portfolio is preset from the
        normal run's in-memory valuations (no repricing); standalone it is built.
        """
        if self._priced is None:
            from .priced import PricedPortfolio

            self._priced = PricedPortfolio.build(self.val_date, self.data_dir)
        return self._priced

    def set_priced(self, priced: "PricedPortfolio") -> None:
        self._priced = priced


# A producer takes (ctx, dest_dir) and returns the files written.
Producer = Callable[[RunContext, Path], list[Path]]


@dataclass(frozen=True)
class AdditionalOutput:
    """One registered additional-output item."""

    name: str
    frequency: Frequency
    channel: Channel
    produce: Producer


def is_due(freq: Frequency, val_date: date) -> bool:
    """True if a *calendar-driven* item of ``freq`` is due for ``val_date``.

    ``ONCE`` is never calendar-due (gated by ``--new-deal-<id>``); see
    :func:`should_run`. Frequencies are independent predicates: a quarter-end
    date is also a month-end, so both fire on Mar/Jun/Sep/Dec EOM.
    """
    if freq is Frequency.DAILY:
        return True
    if freq is Frequency.MONTH_END:
        return is_month_end(val_date)
    if freq is Frequency.QUARTER_END:
        return is_month_end(val_date) and val_date.month in _QUARTER_END_MONTHS
    if freq is Frequency.ONCE:
        return False
    raise ValueError(f"Unknown frequency: {freq!r}")


def should_run(item: AdditionalOutput, val_date: date, new_deal_ids: frozenset[str], force: bool = False) -> bool:
    """Whether ``item`` runs this invocation."""
    if force:
        return True
    if item.frequency is Frequency.ONCE:
        return bool(new_deal_ids)
    return is_due(item.frequency, val_date)


def resolve_channel_dir(channel: Channel, run_dir: Path) -> Path:
    """Destination directory for a channel, relative to this run's dated folder.

    * SFTP  -> ``run_dir`` (alongside the IRS Valuation feed).
    * EMAIL -> ``run_dir/email`` (a subfolder of the dated run folder).
    """
    if channel is Channel.EMAIL:
        return run_dir / "email"
    if channel is Channel.SFTP:
        return run_dir
    raise ValueError(f"Unknown channel: {channel!r}")
