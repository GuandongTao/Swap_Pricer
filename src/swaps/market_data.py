"""Bundle of market inputs used by the pricer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .curve import ZeroCurve
from .fixings import FixingHistory


@dataclass(frozen=True)
class MarketData:
    val_date: date
    discount_curve: ZeroCurve   # SOFR
    projection_curve: ZeroCurve  # Fed Funds
    fixings: FixingHistory
