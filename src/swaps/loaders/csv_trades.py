"""CSV-based trade loader.

One CSV file holds many trades, one row per trade. Header names match the
:class:`TradeDef` field names. Empty cells use the dataclass defaults.

Required columns (any subset of the following will be respected; defaults
apply for missing optional columns):

    trade_id, notional, pay_fixed, fixed_rate,
    start_date, maturity_date, fixed_frequency, fixed_daycount,
    floating_daycount, floating_spread,
    fixing_calendar, payment_calendar,
    payment_delay_bdays, lockout_bdays, business_day_convention,
    description

Lines beginning with ``#`` are treated as comments and skipped.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

from .base import TradeDef, TradeLoader


def _to_bool(v) -> bool:
    s = str(v).strip().lower()
    if s in ("true", "1", "yes", "y", "t"):
        return True
    if s in ("false", "0", "no", "n", "f"):
        return False
    raise ValueError(f"Cannot parse boolean from {v!r}")


def _to_date(v) -> date:
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    s = str(v).strip()
    # Try ISO first, then US-style M/D/YYYY
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return pd.to_datetime(s).date()


def _parse_row(row: dict) -> TradeDef:
    def get(field, default=None, parser=None):
        v = row.get(field)
        if v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, float) and pd.isna(v)):
            return default
        return parser(v) if parser else v

    return TradeDef(
        trade_id=str(row["trade_id"]).strip(),
        notional=float(row["notional"]),
        pay_fixed=_to_bool(row["pay_fixed"]),
        fixed_rate=float(row["fixed_rate"]),
        start_date=_to_date(row["start_date"]),
        maturity_date=_to_date(row["maturity_date"]),
        fixed_frequency=str(row["fixed_frequency"]).strip(),
        fixed_daycount=str(row["fixed_daycount"]).strip(),
        floating_daycount=get("floating_daycount", "ACT/360", str),
        floating_spread=get("floating_spread", 0.0, float),
        fixing_calendar=get("fixing_calendar", "NY_FED", str),
        payment_calendar=get("payment_calendar", "NY_FED", str),
        payment_delay_bdays=get("payment_delay_bdays", 0, int),
        lockout_bdays=get("lockout_bdays", 0, int),
        business_day_convention=get("business_day_convention", "ModifiedFollowing", str),
        meta={"description": get("description", "", str)} if get("description") else {},
    )


class CsvTradeLoader(TradeLoader):
    """Load all trade rows from one or more CSV files in a directory."""

    def __init__(self, trades_dir: str | Path) -> None:
        self.trades_dir = Path(trades_dir)

    def _csv_files(self) -> Iterable[Path]:
        return sorted(p for p in self.trades_dir.glob("*.csv") if not p.name.startswith("_"))

    def load_all(self) -> list[TradeDef]:
        out: list[TradeDef] = []
        for p in self._csv_files():
            df = pd.read_csv(p, comment="#", skip_blank_lines=True)
            if "trade_id" not in df.columns:
                raise ValueError(f"{p}: CSV must include a 'trade_id' column")
            df = df.dropna(how="all")
            for _, row in df.iterrows():
                if pd.isna(row.get("trade_id")) or not str(row["trade_id"]).strip():
                    continue
                out.append(_parse_row(row.to_dict()))
        return out

    def load(self, trade_id: str) -> TradeDef:
        for t in self.load_all():
            if t.trade_id == trade_id:
                return t
        raise KeyError(f"Trade {trade_id!r} not found in {self.trades_dir}")
