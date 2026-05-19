"""CSV-based trade loader.

One CSV holds many trades, one row per trade. Header names match
:class:`TradeDef` (Bloomberg vocabulary). Empty cells use the dataclass
default. Only economic terms are required.

Bloomberg-derived fields auto-sync (leave the column blank / omit it):
  * ``*_pay_date_adj``      blank -> that leg's ``*_bus_day_adj``
  * ``*_payment_calendar``  blank -> that leg's ``*_calculation_calendar``
  * ``floating_reset_lag_bdays`` default 0 (in-arrears OIS has no lookback)

Lines beginning with ``#`` are comments and skipped.
"""

from __future__ import annotations

import io
from dataclasses import fields
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

from .base import TradeDef, TradeLoader

_DATE_FIELDS = {"start_date", "maturity_date"}
_FLOAT_FIELDS = {"notional", "fixed_rate", "floating_spread"}
_BOOL_FIELDS = {"pay_fixed"}
_INT_FIELDS = {
    "fixed_payment_delay_bdays", "floating_payment_delay_bdays",
    "floating_reset_lag_bdays", "floating_lockout_bdays",
}
_DATELIST_FIELDS = {
    "fixed_calculation_calendar_extras", "fixed_payment_calendar_extras",
    "floating_calculation_calendar_extras", "floating_fixing_calendar_extras",
    "floating_payment_calendar_extras",
}
_FIELD_NAMES = {f.name for f in fields(TradeDef)} - {"meta"}
_REQUIRED = {
    "trade_id", "notional", "pay_fixed", "fixed_rate",
    "start_date", "maturity_date", "fixed_frequency", "fixed_daycount",
}


def _strip_comment_lines(text: str) -> str:
    keep = []
    for line in text.splitlines():
        s = line.lstrip()
        if s.startswith("#") or s.startswith('"#'):
            continue
        keep.append(line)
    return "\n".join(keep)


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
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return pd.to_datetime(s).date()


def _to_date_list(v) -> list[date]:
    s = str(v).strip()
    if not s:
        return []
    return [_to_date(x) for x in s.replace(";", ",").split(",") if x.strip()]


def _blank(v) -> bool:
    return (
        v is None
        or (isinstance(v, str) and not v.strip())
        or (isinstance(v, float) and pd.isna(v))
    )


def _parse_row(row: dict) -> TradeDef:
    missing = _REQUIRED - {k for k, v in row.items() if not _blank(v)}
    if missing:
        raise ValueError(f"CSV row {row.get('trade_id')!r} missing required: {sorted(missing)}")

    raw_id = str(row["trade_id"]).strip()
    meta: dict = {"id": raw_id, "_id_scheme": "amex_daily_irs"}
    desc = row.get("description")
    if not _blank(desc):
        meta["description"] = str(desc)

    kwargs: dict = {}
    for name in _FIELD_NAMES:
        if name not in row or _blank(row[name]):
            continue
        v = row[name]
        if name in _DATE_FIELDS:
            kwargs[name] = _to_date(v)
        elif name in _FLOAT_FIELDS:
            kwargs[name] = float(v)
        elif name in _BOOL_FIELDS:
            kwargs[name] = _to_bool(v)
        elif name in _INT_FIELDS:
            kwargs[name] = int(float(v))
        elif name in _DATELIST_FIELDS:
            kwargs[name] = _to_date_list(v)
        else:
            kwargs[name] = str(v).strip()

    # CSV trades follow the AMEX daily-IRS naming scheme: the trade_id column
    # carries ONLY the trailing unique id; Portfolio.run reconstructs the full
    # id once the val_date is known.
    kwargs["trade_id"] = raw_id
    return TradeDef(**kwargs, meta=meta)


class CsvTradeLoader(TradeLoader):
    """Load all trade rows from one or more CSV files in a directory."""

    def __init__(self, trades_dir: str | Path) -> None:
        self.trades_dir = Path(trades_dir)

    def _csv_files(self) -> Iterable[Path]:
        return sorted(p for p in self.trades_dir.glob("*.csv") if not p.name.startswith("_"))

    def load_all(self) -> list[TradeDef]:
        out: list[TradeDef] = []
        for p in self._csv_files():
            text = _strip_comment_lines(p.read_text(encoding="utf-8-sig"))
            df = pd.read_csv(io.StringIO(text), skip_blank_lines=True)
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
