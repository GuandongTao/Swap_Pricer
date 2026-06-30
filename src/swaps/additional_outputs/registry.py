"""Registry of additional-output items.

Mirrors ``additional output templates/frequency and channel.xlsx``. Add one
``AdditionalOutput`` per item as specs are locked.

Not yet registered (left for later per the templates):
  * AmexIntExp              -- empty placeholder (PENDING)
  * FVH Attribution         -- needs a design discussion (PENDING)

Note: "Monthly" cadence is coded as month-end pending confirmation (affects
Hedge Summary; see _intake.md).
"""

from __future__ import annotations

from . import (
    day1_valuations,
    hedge_summary,
    month_end_data,
    payment_report,
    swap_payment_schedule,
    treasury_valuation,
    valuation_report,
)
from .base import AdditionalOutput, Channel, Frequency

REGISTRY: list[AdditionalOutput] = [
    AdditionalOutput("Month End Data", Frequency.MONTH_END, Channel.EMAIL, month_end_data.produce),
    AdditionalOutput("Hedge Summary", Frequency.MONTH_END, Channel.SFTP, hedge_summary.produce),
    AdditionalOutput("Treasury Valuation Report", Frequency.MONTH_END, Channel.SFTP, treasury_valuation.produce),
    AdditionalOutput("KPMG Payment Report", Frequency.DAILY, Channel.SFTP, payment_report.produce),
    AdditionalOutput("KPMG Valuation Report", Frequency.DAILY, Channel.SFTP, valuation_report.produce),
    AdditionalOutput("Swap Payment Schedule", Frequency.ONCE, Channel.SFTP, swap_payment_schedule.produce),
    AdditionalOutput("Day 1 Valuations", Frequency.ONCE, Channel.EMAIL, day1_valuations.produce),
]
