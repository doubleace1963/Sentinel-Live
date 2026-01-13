from __future__ import annotations

import time
from datetime import datetime
from typing import Optional

import MetaTrader5 as mt5
import Live1.mt5_adapter as mt5a
from Live1.strategy.select_setup import Setup


def place_setup_limit_order(
    *,
    setup: Setup,
    retries: int,
    retry_delay_seconds: float,
    deviation_points: int,
    magic: int,
    comment: str,
    expiration: Optional[datetime] = None,
):
    side = "buy" if setup.fvg_type == "Bullish" else "sell"

    last_result = None
    for attempt in range(1, max(1, int(retries)) + 1):
        last_result = mt5a.place_limit_order(
            symbol=setup.symbol,
            side=side,
            volume=setup.volume,
            price=setup.entry_price_adjusted,
            sl=setup.stop_loss,
            tp=setup.take_profit,
            deviation_points=deviation_points,
            magic=magic,
            comment=comment,
            expiration=expiration,
        )

        if last_result is not None and getattr(last_result, "retcode", None) == mt5.TRADE_RETCODE_DONE:
            return last_result

        time.sleep(float(retry_delay_seconds))

    return last_result
