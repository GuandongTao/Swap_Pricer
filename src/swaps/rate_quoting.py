"""Zero-rate quoting conventions: rate <-> discount factor at a given tenor.

Default = ContinuousACT360 (assumption Q2 in questions.md).
Switching conventions is a one-line change at curve construction.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod


class RateQuoting(ABC):
    """Maps zero rate <-> discount factor for a tenor expressed in calendar days."""

    name: str

    @abstractmethod
    def rate_to_df(self, rate: float, days: int) -> float: ...

    @abstractmethod
    def df_to_rate(self, df: float, days: int) -> float: ...

    def __repr__(self) -> str:
        return f"RateQuoting({self.name})"


class ContinuousACT360(RateQuoting):
    """Continuously compounded, ACT/360 day count. ``DF = exp(-r * days/360)``.
    Default convention; benchmarked against Bloomberg for USD SOFR/FF curves."""

    name = "ContinuousACT360"

    def rate_to_df(self, rate: float, days: int) -> float:
        return math.exp(-rate * days / 360.0)

    def df_to_rate(self, df: float, days: int) -> float:
        return -math.log(df) * 360.0 / days


class SimpleACT360(RateQuoting):
    """Simple (money-market) rate, ACT/360. ``DF = 1 / (1 + r * days/360)``."""

    name = "SimpleACT360"

    def rate_to_df(self, rate: float, days: int) -> float:
        return 1.0 / (1.0 + rate * days / 360.0)

    def df_to_rate(self, df: float, days: int) -> float:
        return (1.0 / df - 1.0) * 360.0 / days


class ContinuousACT365(RateQuoting):
    """Continuously compounded, ACT/365 day count. ``DF = exp(-r * days/365)``."""

    name = "ContinuousACT365"

    def rate_to_df(self, rate: float, days: int) -> float:
        return math.exp(-rate * days / 365.0)

    def df_to_rate(self, df: float, days: int) -> float:
        return -math.log(df) * 365.0 / days


class AnnualCompoundedACT365(RateQuoting):
    """Annually compounded, ACT/365. ``DF = (1 + r)^(-days/365)``."""

    name = "AnnualCompoundedACT365"

    def rate_to_df(self, rate: float, days: int) -> float:
        return (1.0 + rate) ** (-days / 365.0)

    def df_to_rate(self, df: float, days: int) -> float:
        return df ** (-365.0 / days) - 1.0


class AnnualCompoundedACT360(RateQuoting):
    """Annually compounded, ACT/360. ``DF = (1 + r)^(-days/360)``."""

    name = "AnnualCompoundedACT360"

    def rate_to_df(self, rate: float, days: int) -> float:
        return (1.0 + rate) ** (-days / 360.0)

    def df_to_rate(self, df: float, days: int) -> float:
        return df ** (-360.0 / days) - 1.0


_REGISTRY: dict[str, RateQuoting] = {
    cls().name: cls() for cls in (
        ContinuousACT360, SimpleACT360, ContinuousACT365,
        AnnualCompoundedACT365, AnnualCompoundedACT360,
    )
}


def get_rate_quoting(name: str) -> RateQuoting:
    try:
        return _REGISTRY[name]
    except KeyError as e:
        raise ValueError(f"Unknown RateQuoting {name!r}; known: {sorted(_REGISTRY)}") from e


# Default quoting convention used by ZeroCurve / ExcelCurveLoader unless overridden.
# 2026-05-12: ContinuousACT360
# 2026-05-13 (am): AnnualCompoundedACT360
# 2026-05-13 (pm): ContinuousACT360 -- annual-comp DFs ran high vs benchmark;
#   continuous lowers DF uniformly (e^(-rT) < (1+r)^(-T) for r,T > 0).
DEFAULT = ContinuousACT360()
