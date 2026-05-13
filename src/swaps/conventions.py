"""Day-count conventions as strategy classes.

Each strategy exposes ``year_fraction(d1, d2) -> float``. Add new conventions
by subclassing ``DayCount``; no edits to legs or pricer are needed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Literal

DayCountName = Literal["ACT/360", "ACT/365F", "30/360", "30E/360", "ACT/ACT-ISDA"]


class DayCount(ABC):
    name: DayCountName

    @abstractmethod
    def year_fraction(self, d1: date, d2: date) -> float: ...

    def __repr__(self) -> str:
        return f"DayCount({self.name})"


class Act360(DayCount):
    name = "ACT/360"

    def year_fraction(self, d1: date, d2: date) -> float:
        return (d2 - d1).days / 360.0


class Act365F(DayCount):
    name = "ACT/365F"

    def year_fraction(self, d1: date, d2: date) -> float:
        return (d2 - d1).days / 365.0


class Thirty360(DayCount):
    """30/360 ISDA (a.k.a. bond basis)."""

    name = "30/360"

    def year_fraction(self, d1: date, d2: date) -> float:
        d1d = min(d1.day, 30)
        d2d = 30 if (d1d == 30 and d2.day == 31) else d2.day
        return ((d2.year - d1.year) * 360 + (d2.month - d1.month) * 30 + (d2d - d1d)) / 360.0


class ThirtyE360(DayCount):
    """30E/360 (European)."""

    name = "30E/360"

    def year_fraction(self, d1: date, d2: date) -> float:
        d1d = min(d1.day, 30)
        d2d = min(d2.day, 30)
        return ((d2.year - d1.year) * 360 + (d2.month - d1.month) * 30 + (d2d - d1d)) / 360.0


class ActActIsda(DayCount):
    name = "ACT/ACT-ISDA"

    def year_fraction(self, d1: date, d2: date) -> float:
        if d1 == d2:
            return 0.0
        if d1 > d2:
            return -self.year_fraction(d2, d1)
        total = 0.0
        y = d1.year
        while y < d2.year:
            year_end = date(y + 1, 1, 1)
            denom = 366.0 if _is_leap(y) else 365.0
            total += (year_end - (d1 if y == d1.year else date(y, 1, 1))).days / denom
            y += 1
        denom = 366.0 if _is_leap(d2.year) else 365.0
        total += (d2 - date(d2.year, 1, 1)).days / denom
        return total


def _is_leap(y: int) -> bool:
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


_REGISTRY: dict[str, DayCount] = {
    "ACT/360": Act360(),
    "ACT/365F": Act365F(),
    "30/360": Thirty360(),
    "30E/360": ThirtyE360(),
    "ACT/ACT-ISDA": ActActIsda(),
}


def get_daycount(name: str) -> DayCount:
    """Look up a day-count convention by canonical name."""
    try:
        return _REGISTRY[name.upper().replace(" ", "")]
    except KeyError as e:
        raise ValueError(
            f"Unknown day-count {name!r}; known: {sorted(_REGISTRY)}"
        ) from e


# Convenience singletons
ACT_360 = _REGISTRY["ACT/360"]
ACT_365F = _REGISTRY["ACT/365F"]
THIRTY_360 = _REGISTRY["30/360"]
THIRTY_E_360 = _REGISTRY["30E/360"]
ACT_ACT_ISDA = _REGISTRY["ACT/ACT-ISDA"]
