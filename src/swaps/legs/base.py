"""Leg ABC."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

import pandas as pd

from ..curve import ZeroCurve


class Leg(ABC):
    """A cashflow-producing leg of a swap."""

    @abstractmethod
    def cashflows(self, val_date: date, discount_curve: ZeroCurve) -> pd.DataFrame:
        """Return a DataFrame of cashflows with discount-related columns populated."""

    def pv(self, val_date: date, discount_curve: ZeroCurve) -> float:
        df = self.cashflows(val_date, discount_curve)
        if "discounted_cashflow" not in df.columns:
            return 0.0
        return float(df["discounted_cashflow"].sum(skipna=True))

    @abstractmethod
    def accrued(self, val_date: date) -> float:
        """Undiscounted accrued amount as of `val_date`."""
