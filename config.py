from dataclasses import dataclass


@dataclass(frozen=True)
class LiveConfig:
    # Strategy scan
    min_candle_size_pips: int = 50
    lookback_days: int = 7

    # Risk / execution
    risk_per_trade_pct: float = 0.5
    retries: int = 5
    retry_delay_seconds: float = 2.0
    deviation_points: int = 20

    # Pending order behaviour
    cancel_unfilled_at_end_of_day: bool = True

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
    magic_number: int = 19631963
    order_comment: str = "Sentinel"

    # Trading mode: "conservative" (default) or "aggressive"
    # Conservative: Take 50% profit at 3R, move SL to breakeven on remaining position
    # Aggressive: No partial profit taking, hold full position until TP or SL
    trading_mode: str = "conservative"

    # Symbols
    # If empty/None, the app will trade all detected forex symbols from MT5.
    symbols: tuple[str, ...] | None = None
    
    def __post_init__(self):
        # Validate trading_mode
        if self.trading_mode.lower() not in ("conservative", "aggressive"):
            object.__setattr__(self, "trading_mode", "conservative")


CONFIG = LiveConfig()
