"""
Pattern detection logic - copied from Demo1 for standalone Live1 operation.
This module contains the core strategy pattern detection functions.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

import pandas as pd
import MetaTrader5 as mt5


def is_bullish(candle) -> bool:
    """Check if a candle is bullish (close > open)."""
    return candle['close'] > candle['open']


def is_large_candle(candle, symbol: str, min_candle_size_pips: int) -> bool:
    """Check if candle body size meets minimum pip requirement."""
    info = mt5.symbol_info(symbol)
    if info is None:
        return False
    body_size = abs(candle['close'] - candle['open'])
    point_value = info.point
    if not point_value:
        return False
    pips = body_size / point_value
    return pips >= min_candle_size_pips


def detect_exhaustion_pattern(c1, c2, symbol: str, min_candle_size_pips: int) -> bool:
    """
    Return True if two-candle exhaustion pattern is present.
    
    Requirements:
    - C1 must be a large candle (>= min_candle_size_pips)
    - For Bullish C1: C2.high > C1.high AND C1.open < C2.close < C1.high
    - For Bearish C1: C2.low < C1.low AND C1.low < C2.close < C1.open
    """
    if not is_large_candle(c1, symbol, min_candle_size_pips):
        return False

    if is_bullish(c1):
        goes_above = c2['high'] > c1['high']
        closes_in_range = (c1['open'] < c2['close'] < c1['high'])
        return goes_above and closes_in_range
    else:
        goes_below = c2['low'] < c1['low']
        closes_in_range = (c1['low'] < c2['close'] < c1['open'])
        return goes_below and closes_in_range


def get_c1_midpoint(symbol: str, c2_date: pd.Timestamp) -> Optional[float]:
    """
    Get C1 daily candle (day before C2) and calculate its midpoint.
    Midpoint = (C1.high + C1.low) / 2
    """
    # Fetch daily candles from a range that includes C2 and C1
    c2_dt = pd.to_datetime(c2_date).to_pydatetime()
    
    # Fetch from 5 days before C2 to ensure we get C1 (accounting for weekends)
    start_date = c2_dt - timedelta(days=5)
    end_date = c2_dt + timedelta(days=1)
    
    daily_candles = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_D1, start_date, end_date)
    
    if daily_candles is None or len(daily_candles) < 2:
        return None
    
    df = pd.DataFrame(daily_candles)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    
    # Find C2 in the data
    c2_candles = df[df['time'].dt.date == c2_dt.date()]
    
    if len(c2_candles) == 0:
        return None
    
    c2_idx = c2_candles.index[0]
    
    # C1 is the candle before C2
    if c2_idx == 0:
        return None
    
    c1 = df.iloc[c2_idx - 1]
    midpoint = (float(c1['high']) + float(c1['low'])) / 2.0
    
    return midpoint


def calculate_sl_level(
    m5_df: pd.DataFrame,
    validation_time: pd.Timestamp,
    fvg_formation_time: pd.Timestamp,
    fvg_type: str
) -> Optional[float]:
    """
    Calculate stop loss level based on price action from validation candle to FVG formation.
    
    For Bullish FVG: Find lowest low in the range (SL below entry)
    For Bearish FVG: Find highest high in the range (SL above entry)
    
    Note: validation_time typically comes BEFORE fvg_formation_time
    """
    # Per strategy definition, validation should occur strictly BEFORE FVG formation.
    if validation_time >= fvg_formation_time:
        return None

    # Get candles from validation to FVG formation (inclusive)
    range_candles = m5_df[
        (m5_df['time'] >= validation_time) &
        (m5_df['time'] <= fvg_formation_time)
    ]
    
    if len(range_candles) == 0:
        return None
    
    if fvg_type == 'Bullish':
        return range_candles['low'].min()
    else:  # Bearish
        return range_candles['high'].max()
