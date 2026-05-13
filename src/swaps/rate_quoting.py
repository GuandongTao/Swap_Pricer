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
    name = "ContinuousACT360"

    def rate_to_df(self, rate: float, days: int) -> float:
        return math.exp(-rate * days / 360.0)

    def df_to_rate(self, df: float, days: int) -> float:
        return -math.log(df) * 360.0 / days


class SimpleACT360(RateQuoting):
    name = "SimpleACT360"

    def rate_to_df(self, rate: float, days: int) -> float:
        return 1.0 / (1.0 + rate * days / 360.0)

    def df_to_rate(self, df: float, days: int) -> float:
        return (1.0 / df - 1.0) * 360.0 / days


class ContinuousACT365(RateQuoting):
    name = "ContinuousACT365"

    def rate_to_df(self, rate: float, days: int) -> float:
        return math.exp(-rate * days / 365.0)

    def df_to_rate(self, df: float, days: int) -> float:
        return -math.log(df) * 365.0 / days


class AnnualCompoundedACT365(RateQuoting):
    name = "AnnualCompoundedACT365"

    def rate_to_df(self, rate: float, days: int) -> float:
        return (1.0 + rate) ** (-days / 365.0)

    def df_to_rate(self, df: float, days: int) -> float:
        return df ** (-365.0 / days) - 1.0


class AnnualCompoundedACT360(RateQuoting):
    """DF(T) = (1 + r)^(-T_days / 360). Time measured ACT/360, compounded annually."""

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
# Switched from ContinuousACT360 -> AnnualCompoundedACT360 on 2026-05-13 per user direction.
DEFAULT = AnnualCompoundedACT360()
