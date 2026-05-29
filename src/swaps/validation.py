"""Two-tier trade-convention validation.

Tier 1 (hard): impossible / unsupported combinations raise ``ValueError`` so a
trade can never be silently mispriced.

Tier 2 (soft): combinations Bloomberg would gray out (but that still price)
return WARNING strings; the Portfolio runner records them in
``manifest.warnings[]``. No ``strict`` flag — everything is accepted, the
risky combos are just made visible.
"""

from __future__ import annotations

from .loaders.base import TradeDef

_ROLL_CONVENTIONS = {"forward", "forward_eom", "backward", "backward_eom"}
_ADJUST = {"acc_and_pay", "pay", "none"}
_THIRTY_DC = {"30/360", "30E/360", "THIRTY_360", "THIRTY_E_360"}

# Hardcoded assumptions (not settings). A trade asking for anything else is a
# hard error rather than a silent mispricing. These arrive via free-form
# trade-file keys that land in TradeDef.meta.
_RESET_KEYS = ("reset_type", "reset", "fixing_type")
_PAYMENT_KEYS = ("payment_type", "pay_type")


def validate_trade(td: TradeDef) -> list[str]:
    """Raise on impossible combos; return a list of soft-warning strings."""
    # ---- Tier 1: hard errors ----
    for leg, rc in (("fixed", td.fixed_roll_convention), ("floating", td.floating_roll_convention)):
        if rc not in _ROLL_CONVENTIONS:
            raise ValueError(
                f"{td.trade_id}: {leg}_roll_convention {rc!r} invalid; "
                f"expected one of {sorted(_ROLL_CONVENTIONS)}"
            )
    for leg, ad in (("fixed", td.fixed_adjust), ("floating", td.floating_adjust)):
        if str(ad).lower() not in _ADJUST:
            raise ValueError(
                f"{td.trade_id}: {leg}_adjust {ad!r} invalid; expected one of {sorted(_ADJUST)}"
            )
    if td.maturity_date <= td.start_date:
        raise ValueError(
            f"{td.trade_id}: maturity_date {td.maturity_date} must be > start_date {td.start_date}"
        )

    # BBG "First Payment Date" override: anchor must lie strictly inside
    # (start_date, maturity_date).
    for leg, anchor in (
        ("fixed", td.fixed_first_period_accrual_end_date),
        ("floating", td.floating_first_period_accrual_end_date),
    ):
        if anchor is not None and not (td.start_date < anchor < td.maturity_date):
            raise ValueError(
                f"{td.trade_id}: {leg}_first_period_accrual_end_date {anchor} "
                f"must lie strictly between start_date {td.start_date} and "
                f"maturity_date {td.maturity_date}."
            )

    meta = td.meta or {}
    for k in _RESET_KEYS:
        if k in meta and str(meta[k]).lower().replace("-", "_") not in ("in_arrears", "arrears"):
            raise ValueError(
                f"{td.trade_id}: {k}={meta[k]!r} unsupported — only in-arrears OIS "
                "reset is implemented."
            )
    for k in _PAYMENT_KEYS:
        if k in meta and str(meta[k]).lower() not in ("coupon", "couponed"):
            raise ValueError(
                f"{td.trade_id}: {k}={meta[k]!r} unsupported — only Coupon payment "
                "type is implemented."
            )

    # ---- Tier 2: soft warnings (Bloomberg grays these out) ----
    warnings: list[str] = []
    for leg, adjust, roll, dc in (
        ("fixed", td.fixed_adjust, td.fixed_roll_convention, td.fixed_daycount),
        ("floating", td.floating_adjust, td.floating_roll_convention, td.floating_daycount),
    ):
        if str(adjust).lower() == "acc_and_pay" and str(dc) in _THIRTY_DC:
            warnings.append(
                f"{td.trade_id}: {leg} adjust=acc_and_pay with a 30/360-family "
                f"day-count ({dc}) — adjusting accrual dates is economically "
                f"meaningless under 30/360; Bloomberg would use adjust=pay."
            )
    return warnings
