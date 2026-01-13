from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

import Live1.mt5_adapter as mt5a


@dataclass(frozen=True)
class SizingResult:
    volume: float
    risk_amount: float
    risk_per_lot: float


def _round_down_to_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    return math.floor(value / step) * step


def calc_volume_by_risk(
    symbol: str,
    entry_price: float,
    stop_loss: float,
    risk_pct: float,
) -> Optional[SizingResult]:
    info = mt5a.get_symbol_info(symbol)
    acct = mt5a.account_info()
    if info is None or acct is None:
        return None

    balance = float(getattr(acct, "balance", 0.0) or 0.0)
    if balance <= 0:
        return None

    risk_amount = balance * (float(risk_pct) / 100.0)

    tick_value = float(getattr(info, "trade_tick_value", 0.0) or 0.0)
    tick_size = float(getattr(info, "trade_tick_size", 0.0) or 0.0)
    if tick_value <= 0 or tick_size <= 0:
        return None

    price_distance = abs(float(entry_price) - float(stop_loss))
    if price_distance <= 0:
        return None

    # For 1 lot, P/L per tick is tick_value.
    # Number of ticks to SL = price_distance / tick_size.
    risk_per_lot = (price_distance / tick_size) * tick_value
    if risk_per_lot <= 0:
        return None

    raw_lots = risk_amount / risk_per_lot

    vol_min = float(getattr(info, "volume_min", 0.0) or 0.0)
    vol_max = float(getattr(info, "volume_max", 0.0) or 0.0)
    vol_step = float(getattr(info, "volume_step", 0.01) or 0.01)

    lots = _round_down_to_step(raw_lots, vol_step)
    if vol_min > 0:
        lots = max(lots, vol_min)
    if vol_max > 0:
        lots = min(lots, vol_max)

    if lots <= 0:
        return None

    return SizingResult(volume=lots, risk_amount=risk_amount, risk_per_lot=risk_per_lot)
