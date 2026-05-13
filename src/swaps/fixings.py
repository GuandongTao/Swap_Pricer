"""Historical fixing lookups.

For dates earlier than `val_date`, the floating leg consults `FixingHistory` for
the realized rate. `get(d)` returns ``None`` when no record exists, allowing the
caller to fall back to the projection curve.
"""

from __future__ import annotations

from datetime import date

import pandas as pd


class FixingHistory:
    """Date -> rate lookup. Missing -> None."""

    def __init__(self, fixings: dict[date, float] | pd.Series | None = None, name: str = "") -> None:
        self.name = name
        if fixings is None:
            self._map: dict[date, float] = {}
        elif isinstance(fixings, pd.Series):
            self._map = {pd.Timestamp(k).date(): float(v) for k, v in fixings.items()}
        else:
            self._map = {k: float(v) for k, v in fixings.items()}

    def get(self, d: date) -> float | None:
        return self._map.get(d)

    def __contains__(self, d: date) -> bool:
        return d in self._map

    def __len__(self) -> int:
        return len(self._map)

    def to_debug_frame(self) -> pd.DataFrame:
        items = sorted(self._map.items())
        return pd.DataFrame({"date": [d for d, _ in items], "rate": [r for _, r in items]})
