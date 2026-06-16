"""Hedged-debt valuation for the IRS Valuation feed (col AW, Hedged Debt MTM).

The debt a swap hedges is a fixed-rate bond. Its Clean / Accrued / Dirty are
**computed every run** with the same :class:`~swaps.legs.fixed_leg.FixedLeg`
model used for the IRS fixed leg (principal redeemed at maturity), discounted on
the **Fed Funds** curve. The results are written to ``Debt_Summary_<val_date>.csv``
(a run artifact) and feed IRS col AW.

A trade's ``hedge`` direction decides AW:

* ``LH`` -> the hedged debt's ``Clean + USD Outstanding`` (face), looked up by
  the trade's inline ``debt_deal_number``. Original sign is preserved. The
  ``Clean + Outstanding`` definition is preserved from the legacy
  externally-produced summary; we now compute the inputs ourselves.
* ``SC`` -> the swap's own clean value with its sign reversed (``-swap_clean``);
  no debt valuation needed.

The IRS->debt mapping is carried inline (this row's ``trade_id`` is the IRS deal
number; ``debt_deal_number`` is the debt key), so the old
``data/debt/Deal_Numbers.csv`` map is no longer used.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from .curve import ZeroCurve
from .io_prod import write_csv_no_trailing_newline
from .loaders.base import TradeDef
from .trade_builder import build_debt_leg


def _norm_deal(x: object) -> str:
    """Normalize a deal number to a bare string key.

    Deal numbers arrive as ints, strings, or pandas floats (``19085763.0``).
    Strip whitespace and a spurious trailing ``.0`` so every source keys
    identically."""
    if x is None:
        return ""
    s = str(x).strip()
    if s.endswith(".0") and s[:-2].lstrip("-").isdigit():
        s = s[:-2]
    return s


def debt_summary_filename(val_date: date) -> str:
    """Run-artifact filename: ``Debt_Summary_<YYYY-MM-DD>.csv``."""
    return f"Debt_Summary_{val_date.isoformat()}.csv"


def debt_discount_curve(td: TradeDef, ff_curve: ZeroCurve) -> ZeroCurve:
    """The curve used to discount the debt: Fed Funds shifted up by the debt's
    credit/discounting spread (``debt_discount_spread``, decimal, may be
    negative). Returns ``ff_curve`` unchanged when the spread is zero."""
    s = td.debt_discount_spread
    return ff_curve.bumped(s) if s else ff_curve


def value_debt(td: TradeDef, ff_curve: ZeroCurve, val_date: date) -> dict[str, float]:
    """Compute the hedged bond's Clean / Accrued / Dirty as of ``val_date``,
    signed from the **obligor's** perspective (the party that owes the debt).

    Discounted on Fed Funds plus the debt's credit spread
    (``debt_discount_spread``); see :func:`debt_discount_curve`. ``FixedLeg.pv``
    / ``.accrued`` give the bond*holder's* (lender) positive PV; we negate to the
    obligor's view, so Clean / Accrued / Dirty are liabilities (negative). Dirty
    = -(PV of remaining coupons + principal); Accrued uses the same
    inclusive-of-val_date convention as the IRS fixed leg; Clean = Dirty -
    Accrued. Col AW is then ``Clean (negative) + USD Outstanding (positive)``.
    """
    leg = build_debt_leg(td)
    disc = debt_discount_curve(td, ff_curve)
    dirty = -leg.pv(val_date, disc)
    accrued = -leg.accrued(val_date)
    return {"clean": dirty - accrued, "accrued": accrued, "dirty": dirty}


def resolve_hedged_debt_mtm(
    trade_id: str,
    hedge: str,
    debt_deal_number: str,
    swap_clean: float,
    debt_mtm_value: float | None = None,
) -> float:
    """Compute the Hedged Debt MTM (col AW) for one trade.

    ``SC`` -> ``-swap_clean`` (the swap's clean value, sign **reversed**).
    ``LH`` -> ``debt_mtm_value``, the hedged debt's pre-computed ``Clean + USD
    Outstanding`` (sign preserved); the caller values the bond (``value_debt``)
    and passes the result in.

    Raises ``ValueError`` (a hard, per-trade error) when ``hedge`` is blank /
    unrecognized, an ``LH`` trade has no ``debt_deal_number``, or its debt could
    not be valued (``debt_mtm_value is None``). The Portfolio runner catches it,
    records the trade in ``manifest.errors[]``, and ends ``status="partial"``.
    """
    h = (hedge or "").strip().upper()
    if h == "SC":
        return -swap_clean
    if h == "LH":
        if not _norm_deal(debt_deal_number):
            raise ValueError(
                f"{trade_id}: hedge=LH requires a debt_deal_number to identify "
                f"the hedged debt."
            )
        if debt_mtm_value is None:
            raise ValueError(
                f"{trade_id}: hedge=LH but the debt could not be valued (the "
                f"debt_* block must be present and priceable)."
            )
        return debt_mtm_value
    raise ValueError(
        f"{trade_id}: 'hedge' must be 'LH' or 'SC' (got {hedge!r}); it is "
        f"required on every trade row for the IRS Valuation feed."
    )


# --- Debt_Summary CSV artifact ----------------------------------------------
# Column order mirrors the legacy externally-produced Deal_Summary so a human
# can diff the two. Accrued/Clean/Dirty are now computed; the rest are sourced
# from the trade's debt_* block (or derived).
DEBT_SUMMARY_FIELDS: list[str] = [
    "Entity", "Oracle Entity", "Debt Deal Number", "Currency Of Issuance",
    "GAAP Category", "Instrument", "Rate Type", "Settlement Date",
    "Debt Maturity Date", "Fixed Coupon", "Local Currency Outstanding",
    "USD Outstanding", "Counterparty", "CUSIP ISN", "Coupon Frequency",
    "Coupon Days Convention", "Accrued Interest", "Clean", "Dirty",
]

# Tenor code -> the words the legacy summary used for "Coupon Frequency".
_FREQ_WORDS = {"1Y": "ANNUAL", "6M": "SEMI ANNUAL", "3M": "QUARTERLY", "1M": "MONTHLY"}


def _fmt(v: object) -> str:
    """Render a Debt_Summary cell. ``None`` -> blank; dates -> mm/dd/yyyy;
    floats via ``repr`` (shortest round-tripping decimal, no silent rounding)."""
    if v is None:
        return ""
    if isinstance(v, date):
        return v.strftime("%m/%d/%Y")
    if isinstance(v, float):
        return "" if v != v else repr(v)
    return str(v)


def debt_summary_row(td: TradeDef, clean: float, accrued: float, dirty: float) -> dict[str, object]:
    """Build one Debt_Summary record from a trade's debt block + computed values."""
    freq = td.debt_frequency or td.fixed_frequency
    # Show the NET valuation coupon (debt_fixed_rate - floating_spread), in
    # percent, rounded to 6dp to drop binary-float display noise (5.23 not
    # 5.229999...). This matches the coupon actually used to value the bond.
    net_coupon_pct = round((td.debt_fixed_rate - td.floating_spread) * 100.0, 6)
    return {
        "Entity": f"AXP {td.oracle_entity_code}".strip(),
        "Oracle Entity": td.oracle_entity_code,
        "Debt Deal Number": _norm_deal(td.debt_deal_number),
        "Currency Of Issuance": td.notional_currency,
        "GAAP Category": td.debt_gaap_category,
        "Instrument": td.debt_instrument,
        "Rate Type": td.debt_rate_type,
        "Settlement Date": td.debt_settlement_date,
        "Debt Maturity Date": td.maturity_date,
        "Fixed Coupon": net_coupon_pct,   # net coupon in percent (5.625)
        "Local Currency Outstanding": td.debt_notional,
        "USD Outstanding": td.debt_notional,
        "Counterparty": td.debt_counterparty,
        "CUSIP ISN": td.debt_cusip,
        "Coupon Frequency": _FREQ_WORDS.get(freq.upper(), freq),
        "Coupon Days Convention": td.debt_daycount,
        "Accrued Interest": accrued,
        "Clean": clean,
        "Dirty": dirty,
    }


def write_debt_summary_csv(out_path: str | Path, rows: list[dict[str, object]]) -> Path:
    """Write the Debt_Summary artifact: row 1 title, row 2 headers, row 3+ data.

    Mirrors the legacy layout (free-form title, then the header row) so it reads
    the same as the file it replaces. UTF-8, no trailing newline.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    all_rows: list[list[str]] = [
        ["Hedged Debt details"],
        list(DEBT_SUMMARY_FIELDS),
        *[[_fmt(r.get(f)) for f in DEBT_SUMMARY_FIELDS] for r in rows],
    ]
    # Reuse the prod feed's writer (UTF-8, no trailing newline, Windows-safe).
    write_csv_no_trailing_newline(out_path, all_rows)
    return out_path
