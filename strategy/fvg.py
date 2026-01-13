from __future__ import annotations

from typing import Dict, List, Tuple

import pandas as pd


def find_extreme_candle_index(m5_df: pd.DataFrame, pattern_type: str) -> int:
    """Find index of M5 candle with lowest low (TB Bullish) or highest high (TB Bearish)."""
    if pattern_type == "TB Bullish":
        return int(m5_df["low"].idxmin())
    return int(m5_df["high"].idxmax())


def is_fvg_filled(fvg_top: float, fvg_bottom: float, subsequent_candles: pd.DataFrame) -> bool:
    for _, candle in subsequent_candles.iterrows():
        if candle["low"] <= fvg_top and candle["high"] >= fvg_bottom:
            return True
    return False


def find_unfilled_fvgs_structural(m5_df: pd.DataFrame, start_idx: int, pattern_type: str) -> List[Dict]:
    """PASS 1: Detect unfilled FVGs only (no validation)."""
    fvgs: List[Dict] = []

    range_df = m5_df.loc[start_idx:].reset_index(drop=True)
    if len(range_df) < 3:
        return fvgs

    for i in range(len(range_df) - 2):
        c1 = range_df.iloc[i]
        c3 = range_df.iloc[i + 2]

        if pattern_type == "TB Bullish":
            if c1.high >= c3.low:
                continue
            bottom, top = c1.high, c3.low
            fvg_type = "Bullish"
        else:
            if c1.low <= c3.high:
                continue
            top, bottom = c1.low, c3.high
            fvg_type = "Bearish"

        subsequent = range_df.iloc[i + 3 :]
        if is_fvg_filled(top, bottom, subsequent):
            continue

        fvgs.append(
            {
                "start_time": c1.time,
                "end_time": range_df.iloc[-1].time,
                "top": float(top),
                "bottom": float(bottom),
                "type": fvg_type,
                "validation_levels": [],
                "is_validated": False,
            }
        )

    return fvgs


def validate_fvgs_by_price_projection(all_candles: pd.DataFrame, fvgs: List[Dict], lookahead: int = 12) -> None:
    """PASS 2: Validate FVGs using price-only projection logic (modifies in-place)."""

    for fvg in fvgs:
        candles = all_candles[all_candles["time"] <= fvg["start_time"]]
        bottom = fvg["bottom"]
        top = fvg["top"]
        fvg_type = fvg["type"]

        validations = []

        for i in range(len(all_candles) - 2):
            c1 = all_candles.iloc[i]
            c2 = all_candles.iloc[i + 1]

            if fvg_type == "Bullish":
                reaction_ok = (
                    c1.close > c1.open
                    and bottom <= c1.close <= top
                    and c2.close < c2.open
                )
                displacement_ok = lambda c: c.close < bottom
            else:
                reaction_ok = (
                    c1.close < c1.open
                    and bottom <= c1.close <= top
                    and c2.close > c2.open
                )
                displacement_ok = lambda c: c.close > top

            if not reaction_ok:
                continue

            for j in range(i + 2, min(i + 2 + lookahead, len(candles))):
                disp_candle = candles.iloc[j]

                if displacement_ok(disp_candle):
                    reaction_level = c2.open
                    fvg_time = fvg["start_time"]
                    violated = False

                    # Continuous check until FVG forms
                    for k in range(j + 1, len(all_candles)):
                        future_candle = all_candles.iloc[k]
                        if future_candle.time >= fvg_time:
                            break

                        if fvg_type == "Bullish" and future_candle.high > reaction_level:
                            violated = True
                            break

                        if fvg_type == "Bearish" and future_candle.low < reaction_level:
                            violated = True
                            break

                    if violated:
                        break

                    validations.append({"level": float(reaction_level), "time": c2.time})
                    break

        if validations:
            fvg["validation_levels"] = validations[-1:]
            fvg["is_validated"] = True
            break
