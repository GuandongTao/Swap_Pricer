"""YAML-based trade loader. One file per trade under a directory.

Field names match :class:`TradeDef` (Bloomberg vocabulary). Only economic
terms are required; every convention has a sensible default. Unknown keys are
preserved in ``TradeDef.meta``.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import date, datetime
from pathlib import Path

import yaml

from .base import TradeDef, TradeLoader

REQUIRED = {
    "trade_id", "notional", "pay_fixed", "fixed_rate",
    "start_date", "maturity_date", "fixed_frequency", "fixed_daycount",
}

_DATE_FIELDS = {
    "start_date", "maturity_date",
    "fixed_first_period_accrual_end_date",
    "floating_first_period_accrual_end_date",
}
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


def _to_date(v) -> date:
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    return datetime.strptime(str(v), "%Y-%m-%d").date()


def _to_date_list(v) -> list[date]:
    if v is None:
        return []
    if not isinstance(v, list):
        raise ValueError(f"Expected list of dates, got {type(v).__name__}")
    return [_to_date(x) for x in v]


def _parse(raw: dict, path: Path) -> TradeDef:
    missing = REQUIRED - raw.keys()
    if missing:
        raise ValueError(f"Trade file {path} missing required fields: {sorted(missing)}")

    kwargs: dict = {}
    for name in _FIELD_NAMES:
        if name not in raw or raw[name] is None:
            continue
        v = raw[name]
        if name in _DATE_FIELDS:
            kwargs[name] = _to_date(v)
        elif name in _FLOAT_FIELDS:
            kwargs[name] = float(v)
        elif name in _BOOL_FIELDS:
            kwargs[name] = bool(v)
        elif name in _INT_FIELDS:
            kwargs[name] = int(v)
        elif name in _DATELIST_FIELDS:
            kwargs[name] = _to_date_list(v)
        else:
            kwargs[name] = str(v)

    meta = {k: v for k, v in raw.items() if k not in _FIELD_NAMES}
    return TradeDef(**kwargs, meta=meta)


class YamlTradeLoader(TradeLoader):
    def __init__(self, trades_dir: str | Path) -> None:
        self.trades_dir = Path(trades_dir)

    def load_all(self) -> list[TradeDef]:
        out: list[TradeDef] = []
        for p in sorted(self.trades_dir.glob("*.yaml")):
            with p.open("r", encoding="utf-8") as fh:
                out.append(_parse(yaml.safe_load(fh), p))
        return out

    def load(self, trade_id: str) -> TradeDef:
        for t in self.load_all():
            if t.trade_id == trade_id:
                return t
        raise KeyError(f"Trade {trade_id!r} not found in {self.trades_dir}")
