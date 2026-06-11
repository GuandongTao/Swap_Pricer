"""Bundle of market inputs used by the pricer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .curve import ZeroCurve
from .fixings import FixingHistory


@dataclass(frozen=True)
class MarketData:
    """Immutable bundle of market inputs for a single valuation date.

    ``discount_curve`` (SOFR) is used to discount all cashflows.
    ``projection_curve`` (Fed Funds) is used to derive forward rates for the
    floating leg. ``fixings`` supplies historical daily realized rates.
    """

    val_date: date
    discount_curve: ZeroCurve   # SOFR
    projection_curve: ZeroCurve  # Fed Funds
    fixings: FixingHistory
