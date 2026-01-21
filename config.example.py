"""
Example configuration file for Live1 trading bot.
Copy this file to config.py and customize for your needs.

IMPORTANT: Never commit your actual config.py with real account settings!
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class LiveConfig:
    # Strategy scan
    min_candle_size_pips: int = 50  # Minimum C2 candle size in pips
    lookback_days: int = 7  # Days to look back for pattern detection

    # Risk / execution
    risk_per_trade_pct: float = 0.5  # Risk 0.5% of account per trade
    retries: int = 5  # Number of retries for order placement
    retry_delay_seconds: float = 2.0  # Delay between retries
    deviation_points: int = 20  # Acceptable slippage in points

    # Pending order behaviour
    cancel_unfilled_at_end_of_day: bool = True  # Cancel unfilled orders at day end

    # Duplicate protection
    # If we already have a pending limit (or position) for the same symbol + side with an entry
    # price within this tolerance, we skip placing another one.
    duplicate_price_tolerance_points: int = 10

    # Spread handling
    # Candle OHLC from MT5 rates is typically bid-based.
    # For BUY LIMIT, trigger condition uses ASK <= price, so to get filled when BID hits the level
    # we add current spread to the limit price (still must remain below current ask to be a valid limit).
    adjust_buy_limit_for_spread: bool = True
    # For SELL LIMIT, trigger condition uses BID >= price and bid-based levels typically already match.
    adjust_sell_limit_for_spread: bool = False

    # Identification
    magic_number: int = 19631963  # CHANGE THIS to a unique number for your bot
    order_comment: str = "Sentinel"  # Comment visible in MT5

    # Trading mode: "conservative" (default) or "aggressive"
    # Conservative: Take 50% profit at 3R, move SL to breakeven on remaining position
    # Aggressive: No partial profit taking, hold full position until TP or SL
    trading_mode: str = "conservative"

    # Symbols
    # Auto-detection: Set to None to automatically detect standard forex pairs
    # The system will handle broker-specific suffixes (.x, z, .raw, .pro, etc.)
    # Examples: EURUSD.x (GoatFunded), EURUSDz (Enxess), EURUSD.raw (ECN)
    symbols: tuple[str, ...] | None = None
    
    # Manual configuration examples:
    # symbols = None  # Auto-detect (recommended for most users)
    # symbols = ("EURUSD.x", "GBPUSD.x", "USDJPY.x")  # Manual list
    
    def __post_init__(self):
        # Validate trading_mode
        if self.trading_mode.lower() not in ("conservative", "aggressive"):
            object.__setattr__(self, "trading_mode", "conservative")


CONFIG = LiveConfig()
