"""Notional schedule abstraction.

`NotionalSchedule` is a callable `date -> float`. Default `ConstantNotional`
returns a single fixed notional. `StepNotional` is a placeholder for future
amortizing schedules (not used yet).
"""

from __future__ import annotations

import bisect
from abc import ABC, abstractmethod
from datetime import date


class NotionalSchedule(ABC):
    @abstractmethod
    def __call__(self, d: date) -> float: ...


class ConstantNotional(NotionalSchedule):
    def __init__(self, notional: float) -> None:
        self.notional = float(notional)

    def __call__(self, d: date) -> float:  # noqa: ARG002 - signature is part of the contract
        return self.notional

    def __repr__(self) -> str:
        return f"ConstantNotional({self.notional:,.2f})"


class StepNotional(NotionalSchedule):
    """Piecewise-constant notional with reductions on given dates.

    `steps` is a list of `(effective_date, new_notional)` pairs sorted by date.
    The first entry's `effective_date` is treated as the start of the schedule;
    on or after each step's date, the notional becomes `new_notional`.
    """

    def __init__(self, steps: list[tuple[date, float]]) -> None:
        if not steps:
            raise ValueError("StepNotional requires at least one step")
        s = sorted(steps, key=lambda x: x[0])
        self._dates = [d for d, _ in s]
        self._values = [float(v) for _, v in s]

    def __call__(self, d: date) -> float:
        i = bisect.bisect_right(self._dates, d) - 1
        if i < 0:
            return self._values[0]
        return self._values[i]
