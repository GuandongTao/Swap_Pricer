"""Priced-portfolio context for additional outputs.

Replicates the minimal market-data + pricing loop from ``Portfolio.run`` (same
loaders, same id qualification, same ``build_swap`` / ``SwapPricer``) so each
``TradeDef`` is paired with its ``SwapValuation`` WITHOUT touching or triggering
the default output writers. Read-only reuse of the pricer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from ..loaders import CombinedTradeLoader
from ..loaders.base import TradeDef
from ..loaders.csv_trades import CsvTradeLoader
from ..loaders.excel import ExcelCurveLoader, ExcelFixingLoader
from ..loaders.yaml_trades import YamlTradeLoader
from ..market_data import MarketData
from ..portfolio import _qualify_amex_id
from ..pricer import BUMP, SwapPricer, SwapValuation
from ..swap import Swap
from ..trade_builder import build_swap

_FIXINGS_FILENAME = "fixing_cail_USD-FEDFUNDS-ON.csv"


@dataclass
class PricedTrade:
    trade: TradeDef
    valuation: SwapValuation
    swap: Swap


@dataclass
class PricedPortfolio:
    val_date: date
    priced: list[PricedTrade]
    md: MarketData | None = None
    errors: list[str] = field(default_factory=list)

    def by_raw_id(self, raw_id: str) -> list[PricedTrade]:
        """Match priced trades by their *raw* id (``meta['id']`` or trade_id).

        Used by ``Once`` items where the user names newly-added swap ids.
        """
        target = str(raw_id).strip()
        out = []
        for pt in self.priced:
            rid = str(pt.trade.meta.get("id", pt.trade.trade_id)).strip()
            if rid == target or str(pt.trade.trade_id).strip() == target:
                out.append(pt)
        return out

    @classmethod
    def build(cls, val_date: date, data_dir: Path) -> "PricedPortfolio":
        dd = Path(data_dir)
        curve_loader = ExcelCurveLoader(dd / "curves")
        fixing_loader = ExcelFixingLoader(dd / "fixings" / _FIXINGS_FILENAME)
        trade_loader = CombinedTradeLoader(
            YamlTradeLoader(dd / "trades"), CsvTradeLoader(dd / "trades")
        )

        # Same fallback-aware curve load as the default pricer (ExcelCurveLoader
        # rolls a weekend/holiday month-end back to the previous business day).
        sofr = curve_loader.load(val_date, "SOFR")
        ff = curve_loader.load(val_date, "FEDFUNDS")
        fixings = fixing_loader.load("FEDFUNDS")
        trades = trade_loader.load_all()

        # Reconstruct AMEX daily-IRS ids now that the val_date is known (same as
        # Portfolio.run); other loaders keep their id.
        for td in trades:
            if td.meta.get("_id_scheme") == "amex_daily_irs":
                full_id, short_id = _qualify_amex_id(td.meta.get("id", td.trade_id), val_date)
                td.trade_id = full_id
                td.meta = {**td.meta, "id": short_id}

        md = MarketData(val_date=val_date, discount_curve=sofr, projection_curve=ff, fixings=fixings)
        pricer = SwapPricer()

        priced: list[PricedTrade] = []
        errors: list[str] = []
        for td in trades:
            if td.maturity_date < val_date:
                continue  # matured: excluded from additional outputs
            try:
                swap = build_swap(td, ff, fixings)
                v = pricer.price(swap, md)
                priced.append(PricedTrade(td, v, swap))
            except Exception as e:  # noqa: BLE001 - collect, keep going
                errors.append(f"{td.trade_id}: {str(e).splitlines()[0][:160]}")
        return cls(val_date=val_date, priced=priced, md=md, errors=errors)


def leg_risk(pt: PricedTrade, md: MarketData) -> dict[str, float]:
    """Per-leg PV01 / DV01 for the Day 1 report (the pricer only exposes total DV01).

    * PV01 = present value of a 1bp fixed-leg annuity (positive).
    * dv01_fixed + dv01_floating == total v.dv01 (parallel +1bp on both curves),
      using the same sign/bump convention as ``SwapPricer._dv01``.
    """
    swap, v = pt.swap, pt.valuation
    sign = -1.0 if swap.pay_fixed else 1.0

    fc = v.fixed_cf
    annuity = 0.0
    if fc is not None and not fc.empty and "flow_type" in fc.columns:
        c = fc[fc["flow_type"] == "coupon"]
        annuity = float(
            (c["day_count_fraction"] * c["notional"] * c["df_to_payment"]).fillna(0.0).sum()
        )
    pv01 = abs(annuity) * BUMP

    bumped_disc = md.discount_curve.bumped(BUMP)
    bumped_proj = md.projection_curve.bumped(BUMP)
    pv_fixed_b = swap.fixed.pv(md.val_date, bumped_disc)
    pv_float_b = swap.floating.with_projection_curve(bumped_proj).pv(md.val_date, bumped_disc)
    dv01_fixed = sign * (v.pv_fixed - pv_fixed_b)
    dv01_floating = (-sign) * (v.pv_floating - pv_float_b)
    return {"pv01": pv01, "dv01_fixed": dv01_fixed, "dv01_floating": dv01_floating}
