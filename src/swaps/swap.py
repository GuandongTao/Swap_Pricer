"""Swap = fixed leg + floating leg + direction."""

from __future__ import annotations

from dataclasses import dataclass, field

from .legs.fixed_leg import FixedLeg
from .legs.floating_leg_ois import OISFloatingLeg


@dataclass
class Swap:
    trade_id: str
    fixed: FixedLeg
    floating: OISFloatingLeg
    pay_fixed: bool = True  # True => party pays fixed, receives floating
    meta: dict = field(default_factory=dict)
