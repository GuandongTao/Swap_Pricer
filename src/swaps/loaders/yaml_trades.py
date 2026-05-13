"""YAML-based trade loader. One file per trade under a directory."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import yaml

from .base import TradeDef, TradeLoader

REQUIRED = {
    "trade_id", "notional", "pay_fixed", "fixed_rate",
    "start_date", "maturity_date", "fixed_frequency", "fixed_daycount",
}


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
    known = REQUIRED | {
        "floating_daycount", "floating_spread",
        "fixed_principal_exchange", "floating_principal_exchange",
        "fixing_calendar", "payment_calendar",
        "fixing_calendar_extras", "payment_calendar_extras",
        "fixing_calendar_extras_file", "payment_calendar_extras_file",
        "payment_delay_bdays", "lockout_bdays", "business_day_convention",
    }
    return TradeDef(
        trade_id=str(raw["trade_id"]),
        notional=float(raw["notional"]),
        pay_fixed=bool(raw["pay_fixed"]),
        fixed_rate=float(raw["fixed_rate"]),
        start_date=_to_date(raw["start_date"]),
        maturity_date=_to_date(raw["maturity_date"]),
        fixed_frequency=str(raw["fixed_frequency"]),
        fixed_daycount=str(raw["fixed_daycount"]),
        floating_daycount=str(raw.get("floating_daycount", "ACT/360")),
        floating_spread=float(raw.get("floating_spread", 0.0)),
        fixed_principal_exchange=str(raw.get("fixed_principal_exchange", "none")),
        floating_principal_exchange=str(raw.get("floating_principal_exchange", "none")),
        fixing_calendar=str(raw.get("fixing_calendar", "NY_FED")),
        payment_calendar=str(raw.get("payment_calendar", "NY_FED")),
        fixing_calendar_extras=_to_date_list(raw.get("fixing_calendar_extras")),
        payment_calendar_extras=_to_date_list(raw.get("payment_calendar_extras")),
        fixing_calendar_extras_file=raw.get("fixing_calendar_extras_file"),
        payment_calendar_extras_file=raw.get("payment_calendar_extras_file"),
        payment_delay_bdays=int(raw.get("payment_delay_bdays", 0)),
        lockout_bdays=int(raw.get("lockout_bdays", 0)),
        business_day_convention=str(raw.get("business_day_convention", "ModifiedFollowing")),
        meta={k: v for k, v in raw.items() if k not in known},
    )


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
