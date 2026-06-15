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
    par_rate: float
    rate_diff_bp: float
    fixed_cf: pd.DataFrame
    floating_cf: pd.DataFrame
    meta: dict = field(default_factory=dict)
    # Monthly-compounded per-period floating view (mirrors the fixed-leg
    # cashflow granularity). Always computed so the detail workbook can emit it
    # without enabling --debug. Empty for matured trades.
    floating_cf_by_period: pd.DataFrame = field(default_factory=pd.DataFrame)


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

    def par_rate(self, swap: Swap, md: MarketData) -> float:
        """Fixed rate that re-prices the swap to zero value *as of* ``val_date``.

        Closed-form (the fixed leg is linear in the rate):

            par = (PV_floating - PV_fixed_principal_exchange) / annuity

        where ``annuity = Σ τ_i · DF_SOFR(t_i) · N_i`` over remaining fixed
        coupon dates (rows with ``payment_date > val_date``; past/just-paid
        rows carry NaN DF and drop out). Recomputed every valuation date from
        that day's curves -- it is *not* the contractual rate. Returns NaN
        when there is no remaining annuity (matured / fully-paid fixed leg).
        """
        fixed_cf = swap.fixed.cashflows(md.val_date, md.discount_curve)
        if fixed_cf.empty:
            return float("nan")
        coupons = fixed_cf[fixed_cf["flow_type"] == "coupon"]
        annuity = float(
            (coupons["day_count_fraction"] * coupons["notional"] * coupons["df_to_payment"])
            .fillna(0.0)
            .sum()
        )
        if abs(annuity) < 1e-12:
            return float("nan")
        pv_fixed_principal = float(
            fixed_cf.loc[fixed_cf["flow_type"] != "coupon", "discounted_cashflow"].sum()
        )
        pv_floating = swap.floating.pv(md.val_date, md.discount_curve)
        return (pv_floating - pv_fixed_principal) / annuity

    # ------------------------------------------------------------------ public
    def price(self, swap: Swap, md: MarketData) -> SwapValuation:
        pv_fixed, pv_float, dirty = self._signed_pv(swap, md)
        accrued = self._accrued(swap, md.val_date)
        clean = dirty - accrued
        dv01 = self._dv01(swap, md)
        par = self.par_rate(swap, md)
        rate_diff_bp = (
            (swap.fixed.fixed_rate - par) * 1e4
            if par == par  # not NaN
            else float("nan")
        )
        fixed_cf = swap.fixed.cashflows(md.val_date, md.discount_curve)
        floating_cf = swap.floating.cashflows(md.val_date, md.discount_curve)
        floating_cf_by_period = swap.floating.period_cashflows(md.val_date, md.discount_curve)
        return SwapValuation(
            trade_id=swap.trade_id,
            val_date=md.val_date,
            clean=clean,
            dirty=dirty,
            accrued=accrued,
            dv01=dv01,
            pv_fixed=pv_fixed,
            pv_floating=pv_float,
            par_rate=par,
            rate_diff_bp=rate_diff_bp,
            fixed_cf=fixed_cf,
            floating_cf=floating_cf,
            meta=dict(swap.meta),
            floating_cf_by_period=floating_cf_by_period,
        )

    def _dv01(self, swap: Swap, md: MarketData) -> float:
        """Parallel-DV01 via a symmetric (central) ±1bp bump of both the SOFR
        (discount) and FF (projection) curves:

            DV01 = [PV(-1bp) - PV(+1bp)] / 2

        i.e. the average of the down-bump gain and the up-bump loss per 1bp.
        Positive DV01 means the position drops in value when rates rise. The
        two-sided difference cancels the second-order (convexity) term that a
        one-sided bump leaves in.
        """
        pv_up = self._bumped_pv(swap, md, self.bump_size)
        pv_down = self._bumped_pv(swap, md, -self.bump_size)
        return (pv_down - pv_up) / 2.0

    def _bumped_pv(self, swap: Swap, md: MarketData, delta: float) -> float:
        """Signed PV with both curves shifted by ``delta`` (in absolute rate
        terms; +1bp = +1e-4). The floating leg is repointed at the bumped
        projection curve so forwards move with the bump."""
        bumped_disc = md.discount_curve.bumped(delta)
        bumped_proj = md.projection_curve.bumped(delta)
        bumped_swap = Swap(
            trade_id=swap.trade_id,
            fixed=swap.fixed,
            floating=swap.floating.with_projection_curve(bumped_proj),
            pay_fixed=swap.pay_fixed,
            meta=dict(swap.meta),
        )
        bumped_md = MarketData(
            val_date=md.val_date,
            discount_curve=bumped_disc,
            projection_curve=bumped_proj,
            fixings=md.fixings,
        )
        _, _, pv = self._signed_pv(bumped_swap, bumped_md)
        return pv
