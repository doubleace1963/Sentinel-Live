from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

import pandas as pd

import Live1.mt5_adapter as mt5a
import Live1.risk as risk
from Live1.strategy import fvg as fvg_lib
from Live1.strategy import pattern_detection as pd_lib


@dataclass(frozen=True)
class Setup:
    symbol: str
    pattern_type: str
    fvg_type: str  # Bullish | Bearish
    c2_time: pd.Timestamp
    validation_level: float
    validation_time: pd.Timestamp
    formation_time: pd.Timestamp
    entry_price: float
    entry_price_adjusted: float
    stop_loss: float
    take_profit: float
    est_r_multiple: float
    volume: float


def _calc_r(entry: float, sl: float, tp: float) -> Optional[float]:
    sl_dist = abs(entry - sl)
    if sl_dist <= 0:
        return None
    return abs(tp - entry) / sl_dist


def _apply_spread_adjustment(symbol: str, fvg_type: str, entry: float, adjust_buy: bool, adjust_sell: bool) -> float:
    spread = mt5a.get_spread_price(symbol)
    if spread is None:
        return entry

    if fvg_type == "Bullish" and adjust_buy:
        return float(entry) + float(spread)
    if fvg_type == "Bearish" and adjust_sell:
        return float(entry) - float(spread)
    return float(entry)


def select_best_r_setup_for_symbol(
    *,
    symbol: str,
    min_candle_size_pips: int,
    lookback_days: int,
    risk_pct: float,
    adjust_buy_limit_for_spread: bool,
    adjust_sell_limit_for_spread: bool,
) -> Optional[Setup]:
    """Return the best-R validated FVG setup for the most recently completed C2 day."""

    daily = mt5a.fetch_daily(symbol, bars=max(lookback_days, 5))
    if daily is None or len(daily) < 4:
        return None

    # Assume last D1 candle is the current (forming) day. C2 and C1 are previous.
    c3 = daily.iloc[-1]
    c2 = daily.iloc[-2]
    c1 = daily.iloc[-3]

    if not pd_lib.detect_exhaustion_pattern(c1, c2, symbol, min_candle_size_pips):
        return None

    pattern_type = "TB Bearish" if pd_lib.is_bullish(c1) else "TB Bullish"

    c2_start = pd.to_datetime(c2["time"]).to_pydatetime().replace(microsecond=0)
    c2_end = c2_start + timedelta(days=1)

    m5_c2 = mt5a.fetch_m5(symbol, c2_start, c2_end)
    if m5_c2 is None or len(m5_c2) < 10:
        return None

    extreme_idx = fvg_lib.find_extreme_candle_index(m5_c2, pattern_type)
    fvgs = fvg_lib.find_unfilled_fvgs_structural(m5_c2, extreme_idx, pattern_type)
    if not fvgs:
        return None

    fvg_lib.validate_fvgs_by_price_projection(m5_c2, fvgs)

    validated = [f for f in fvgs if f.get("is_validated") and f.get("validation_levels")]
    if not validated:
        return None

    best: Optional[Setup] = None
    best_r: float = -1.0

    for f in validated:
        lvl = float(f["validation_levels"][0]["level"])
        vtime = pd.to_datetime(f["validation_levels"][0]["time"])
        formation_time = pd.to_datetime(f["start_time"])
        fvg_type = str(f["type"])

        # Strict rule from your backtest
        if vtime >= formation_time:
            continue

        sl = pd_lib.calculate_sl_level(m5_c2, vtime, formation_time, fvg_type)
        if sl is None:
            continue

        tp = pd_lib.get_c1_midpoint(symbol, pd.to_datetime(c2["time"]))
        if tp is None:
            continue

        # Entry-vs-TP validation
        if fvg_type == "Bullish" and lvl >= tp:
            continue
        if fvg_type == "Bearish" and lvl <= tp:
            continue

        entry_adj = _apply_spread_adjustment(
            symbol,
            fvg_type,
            lvl,
            adjust_buy_limit_for_spread,
            adjust_sell_limit_for_spread,
        )

        r_val = _calc_r(entry_adj, float(sl), float(tp))
        if r_val is None:
            continue

        sizing = risk.calc_volume_by_risk(symbol, entry_adj, float(sl), risk_pct)
        if sizing is None:
            continue

        if r_val > best_r:
            best_r = r_val
            best = Setup(
                symbol=symbol,
                pattern_type=pattern_type,
                fvg_type=fvg_type,
                c2_time=pd.to_datetime(c2["time"]),
                validation_level=lvl,
                validation_time=vtime,
                formation_time=formation_time,
                entry_price=float(lvl),
                entry_price_adjusted=float(entry_adj),
                stop_loss=float(sl),
                take_profit=float(tp),
                est_r_multiple=float(r_val),
                volume=float(sizing.volume),
            )

    return best
