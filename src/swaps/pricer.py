"""Swap pricer: compose leg cashflows into clean / dirty / accrued / DV01.

Sign convention: ``pay_fixed=True`` means the holder pays the fixed leg and
receives the floating leg, so PV = PV(float) - PV(fixed). DV01 is the loss for
a +1bp parallel shift of the SOFR (discount) curve; positive means the
position loses money when rates rise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from .market_data import MarketData
from .swap import Swap

BUMP = 1e-4  # 1 basis point


@dataclass
class SwapValuation:
    trade_id: str
    val_date: date
    clean: float
    dirty: float
    accrued: float
    dv01: float
    pv_fixed: float
    pv_floating: float
    fixed_cf: pd.DataFrame
    floating_cf: pd.DataFrame
    meta: dict = field(default_factory=dict)


class SwapPricer:
    def __init__(self, bump_size: float = BUMP) -> None:
        self.bump_size = bump_size

    # ------------------------------------------------------------------ core
    def _signed_pv(self, swap: Swap, md: MarketData) -> tuple[float, float, float]:
        pv_fixed = swap.fixed.pv(md.val_date, md.discount_curve)
        pv_float = swap.floating.pv(md.val_date, md.discount_curve)
        sign = -1.0 if swap.pay_fixed else 1.0
        dirty = sign * pv_fixed + (-sign) * pv_float
        # = pv_float - pv_fixed (pay-fixed) or pv_fixed - pv_float (receive-fixed)
        return pv_fixed, pv_float, dirty

    def _accrued(self, swap: Swap, val_date: date) -> float:
        sign = -1.0 if swap.pay_fixed else 1.0
        return sign * swap.fixed.accrued(val_date) + (-sign) * swap.floating.accrued(val_date)

    # ------------------------------------------------------------------ public
    def price(self, swap: Swap, md: MarketData) -> SwapValuation:
        pv_fixed, pv_float, dirty = self._signed_pv(swap, md)
        accrued = self._accrued(swap, md.val_date)
        clean = dirty - accrued
        dv01 = self._dv01(swap, md)
        fixed_cf = swap.fixed.cashflows(md.val_date, md.discount_curve)
        floating_cf = swap.floating.cashflows(md.val_date, md.discount_curve)
        return SwapValuation(
            trade_id=swap.trade_id,
            val_date=md.val_date,
            clean=clean,
            dirty=dirty,
            accrued=accrued,
            dv01=dv01,
            pv_fixed=pv_fixed,
            pv_floating=pv_float,
            fixed_cf=fixed_cf,
            floating_cf=floating_cf,
            meta=dict(swap.meta),
        )

    def _dv01(self, swap: Swap, md: MarketData) -> float:
        """Parallel-DV01: shift both SOFR (discount) and FF (projection) curves by +1bp.

        Returns the *loss* under the bump — i.e. ``PV(base) - PV(bumped)``.
        Positive DV01 means the position drops in value when rates rise.
        """
        _, _, base = self._signed_pv(swap, md)
        bumped_disc = md.discount_curve.bumped(self.bump_size)
        bumped_proj = md.projection_curve.bumped(self.bump_size)
        # Rebuild the swap with a floating leg pointing at the bumped projection curve.
        bumped_floating = swap.floating.with_projection_curve(bumped_proj)
        bumped_swap = Swap(
            trade_id=swap.trade_id,
            fixed=swap.fixed,
            floating=bumped_floating,
            pay_fixed=swap.pay_fixed,
            meta=dict(swap.meta),
        )
        bumped_md = MarketData(
            val_date=md.val_date,
            discount_curve=bumped_disc,
            projection_curve=bumped_proj,
            fixings=md.fixings,
        )
        _, _, bumped = self._signed_pv(bumped_swap, bumped_md)
        return base - bumped
