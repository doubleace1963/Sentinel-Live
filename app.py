from __future__ import annotations

import time
from datetime import timedelta

import pandas as pd

from Live1.config import CONFIG
from Live1.storage import JsonStore
import Live1.mt5_adapter as mt5a
from Live1.strategy.select_setup import select_best_r_setup_for_symbol
from Live1.execution import place_setup_limit_order
from Live1.trade_manager import RuntimeTracker, reconcile
from Live1.partial_manager import check_and_execute_partials


def _is_weekend(dt) -> bool:
    # Monday=0 ... Sunday=6
    return int(dt.weekday()) >= 5


def _is_duplicate_trade_intent(*, symbol: str, side: str, entry: float) -> bool:
    """Return True if we already have an order/position near this entry for this symbol/side."""
    info = mt5a.get_symbol_info(symbol)
    point = float(getattr(info, "point", 0.0) or 0.0)
    tol_points = max(0, int(CONFIG.duplicate_price_tolerance_points))
    tol_price = (point * tol_points) if point > 0 else 0.0

    # Pending orders
    for o in mt5a.orders_get_by_magic(CONFIG.magic_number):
        if getattr(o, "symbol", None) != symbol:
            continue
        o_type = int(getattr(o, "type", -1) or -1)
        # 2=BUY_LIMIT, 3=SELL_LIMIT (MT5 constants), but keep it simple by mapping via expected side.
        if side == "buy" and o_type != 2:
            continue
        if side == "sell" and o_type != 3:
            continue
        price_open = float(getattr(o, "price_open", 0.0) or 0.0)
        if tol_price == 0.0:
            if price_open == float(entry):
                return True
        else:
            if abs(price_open - float(entry)) <= tol_price:
                return True

    # Open positions (optional guard against re-placing same intent after a fill)
    for p in mt5a.positions_get_by_magic(CONFIG.magic_number):
        if getattr(p, "symbol", None) != symbol:
            continue
        p_type = int(getattr(p, "type", -1) or -1)  # 0=BUY, 1=SELL
        if side == "buy" and p_type != 0:
            continue
        if side == "sell" and p_type != 1:
            continue
        price_open = float(getattr(p, "price_open", 0.0) or 0.0)
        if tol_price == 0.0:
            if price_open == float(entry):
                return True
        else:
            if abs(price_open - float(entry)) <= tol_price:
                return True

    return False


def _already_traded_today(*, symbol: str, current_d1_start) -> bool:
    """
    Check if we already traded this symbol today by looking at deal history.
    Prevents duplicate orders after restart if state.json was lost/corrupted.
    """
    from datetime import datetime, timedelta
    
    # Check deals from start of current D1 day
    start_time = current_d1_start
    end_time = datetime.now()
    
    deals = mt5a.history_deals_get(start_time, end_time)
    if not deals:
        return False
    
    # Look for any deal (entry or exit) for this symbol with our magic number
    for deal in deals:
        if _safe_int(getattr(deal, "magic", 0)) != int(CONFIG.magic_number):
            continue
        if getattr(deal, "symbol", None) == symbol:
            # Found a deal for this symbol today with our magic
            return True
    
    return False


def _safe_int(x) -> int:
    try:
        return int(x)
    except Exception:
        return 0


def main() -> None:
    store = JsonStore(base_dir=Path(__file__).resolve().parent)
    state = store.load_state()
    tracker = RuntimeTracker(known_order_tickets=set(), known_position_tickets=set())

    if not mt5a.initialize():
        print("MT5 initialize failed")
        return

    store.log_event("startup", {"config": CONFIG.__dict__})
    
    # Validate trading mode
    trading_mode = CONFIG.trading_mode.lower()
    if trading_mode not in ("conservative", "aggressive"):
        print(f"Invalid trading_mode '{CONFIG.trading_mode}', defaulting to conservative")
        trading_mode = "conservative"
    
    print(f"Trading mode: {trading_mode.upper()}")
    if trading_mode == "conservative":
        print("  - Partial profit: 50% at 3R, SL to breakeven")
    else:
        print("  - No partial profit taking")

    try:
        symbols = list(CONFIG.symbols) if CONFIG.symbols else mt5a.get_forex_symbols()
        symbols = [s for s in symbols if mt5a.ensure_symbol(s)]
        print(f"Live1 running on {len(symbols)} symbols")

        while True:
            # Poll MT5 state and log fills/closures.
            state, tracker = reconcile(
                store=store,
                state=state,
                tracker=tracker,
                magic=CONFIG.magic_number,
                cancel_expired=CONFIG.cancel_unfilled_at_end_of_day,
            )
            
            # Check and execute partial profit taking (conservative mode only)
            state = check_and_execute_partials(
                store=store,
                state=state,
                magic=CONFIG.magic_number,
                trading_mode=trading_mode,
            )

            # Weekend awareness: use MT5 tick server time as our clock.
            # On weekends most forex symbols won't tick, but if we do get a tick, we can detect weekend.
            if symbols:
                ref_tick = mt5a.get_tick(symbols[0])
                if ref_tick is not None and _is_weekend(ref_tick.time):
                    weekend_key = ref_tick.time.date().isoformat()
                    if state.last_weekend_notice != weekend_key:
                        store.log_event("weekend_mode", {"date": weekend_key, "server_time": ref_tick.time.isoformat()})
                        state.last_weekend_notice = weekend_key
                        store.save_state(state)

                    # Don't place new orders on weekend; keep looping to maintain logs/state.
                    time.sleep(300)
                    continue

            for symbol in symbols:
                daily = mt5a.fetch_daily(symbol, bars=max(CONFIG.lookback_days, 5))
                if daily is None or len(daily) < 3:
                    continue

                # D1 candle start time of the current forming day
                current_d1_start = pd.to_datetime(daily.iloc[-1]["time"]).to_pydatetime().replace(microsecond=0)
                current_key = current_d1_start.isoformat(timespec="seconds")

                last_key = state.last_d1_start.get(symbol)
                if last_key != current_key:
                    # New day detected for this symbol
                    state.last_d1_start[symbol] = current_key
                    # Clear the order placement tracking for new day
                    if symbol in state.orders_placed:
                        del state.orders_placed[symbol]
                    store.save_state(state)
                    store.log_event("new_day", {"symbol": symbol, "d1_start": current_key})
                    print(f"[{symbol}] New D1 day detected: {current_key}")

                # Check if we already successfully placed an order for this symbol today
                if state.orders_placed.get(symbol) == current_key:
                    continue  # Order already placed for this day, skip
                
                # ADDITIONAL SAFETY: Check deal history to prevent duplicate if state was lost
                if _already_traded_today(symbol=symbol, current_d1_start=current_d1_start):
                    store.log_event(
                        "skip_already_traded_today",
                        {
                            "symbol": symbol,
                            "d1_start": current_key,
                            "reason": "Found deals for this symbol today in history"
                        }
                    )
                    # Mark as placed to prevent re-checking
                    state.orders_placed[symbol] = current_key
                    store.save_state(state)
                    continue

                # Check for valid setup (will check on every scan, allowing retries)
                setup = select_best_r_setup_for_symbol(
                    symbol=symbol,
                    min_candle_size_pips=CONFIG.min_candle_size_pips,
                    lookback_days=CONFIG.lookback_days,
                    risk_pct=CONFIG.risk_per_trade_pct,
                    adjust_buy_limit_for_spread=CONFIG.adjust_buy_limit_for_spread,
                    adjust_sell_limit_for_spread=CONFIG.adjust_sell_limit_for_spread,
                )

                if setup is None:
                    store.log_event("no_setup", {"symbol": symbol})
                    continue

                # Basic sanity: ensure limit price is valid relative to current tick.
                tick = mt5a.get_tick(symbol)
                if tick is None:
                    store.log_event("skip_no_tick", {"symbol": symbol})
                    continue

                if setup.fvg_type == "Bullish":
                    # BUY LIMIT must be below current ask.
                    if setup.entry_price_adjusted >= tick.ask:
                        store.log_event(
                            "skip_invalid_buy_limit",
                            {
                                "symbol": symbol,
                                "entry_adj": setup.entry_price_adjusted,
                                "ask": tick.ask,
                                "spread": tick.ask - tick.bid,
                            },
                        )
                        continue
                else:
                    # SELL LIMIT must be above current bid.
                    if setup.entry_price_adjusted <= tick.bid:
                        store.log_event(
                            "skip_invalid_sell_limit",
                            {
                                "symbol": symbol,
                                "entry_adj": setup.entry_price_adjusted,
                                "bid": tick.bid,
                                "spread": tick.ask - tick.bid,
                            },
                        )
                        continue

                # Duplicate guard: if we already have a matching limit/position near this entry, skip.
                side = "buy" if setup.fvg_type == "Bullish" else "sell"
                if _is_duplicate_trade_intent(symbol=symbol, side=side, entry=setup.entry_price_adjusted):
                    store.log_event(
                        "skip_duplicate",
                        {
                            "symbol": symbol,
                            "side": side,
                            "entry_adj": setup.entry_price_adjusted,
                            "tolerance_points": CONFIG.duplicate_price_tolerance_points,
                        },
                    )
                    continue

                # Expire the order at end of day (optional)
                expiration = None
                if CONFIG.cancel_unfilled_at_end_of_day:
                    expiration = current_d1_start + timedelta(days=1) - timedelta(minutes=1)

                store.log_event(
                    "placing_order",
                    {
                        "symbol": setup.symbol,
                        "pattern_type": setup.pattern_type,
                        "fvg_type": setup.fvg_type,
                        "c2_time": setup.c2_time.isoformat(),
                        "entry": setup.entry_price,
                        "entry_adj": setup.entry_price_adjusted,
                        "sl": setup.stop_loss,
                        "tp": setup.take_profit,
                        "est_r": setup.est_r_multiple,
                        "volume": setup.volume,
                        "expiration": expiration.isoformat() if expiration else None,
                    },
                )

                res = place_setup_limit_order(
                    setup=setup,
                    retries=CONFIG.retries,
                    retry_delay_seconds=CONFIG.retry_delay_seconds,
                    deviation_points=CONFIG.deviation_points,
                    magic=CONFIG.magic_number,
                    comment=CONFIG.order_comment,
                    expiration=expiration,
                )

                if res is None:
                    store.log_event("order_send_failed", {"symbol": setup.symbol, "reason": "order_send returned None"})
                    continue

                retcode = getattr(res, "retcode", None)
                comment = getattr(res, "comment", None)
                
                # Check if order was successfully placed (10009 = Request executed)
                if retcode == 10009:
                    # Mark this symbol as having a successful order placement for today
                    state.orders_placed[symbol] = current_key
                    store.save_state(state)
                    
                    store.log_event(
                        "order_send_result",
                        {
                            "symbol": setup.symbol,
                            "retcode": retcode,
                            "comment": comment,
                            "request_id": getattr(res, "request_id", None),
                            "order": getattr(res, "order", None),
                            "deal": getattr(res, "deal", None),
                        },
                    )
                else:
                    # Order failed (market closed, invalid price, etc.)
                    # Don't mark as placed, will retry on next scan
                    store.log_event(
                        "order_send_failed",
                        {
                            "symbol": setup.symbol,
                            "retcode": retcode,
                            "comment": comment,
                            "request_id": getattr(res, "request_id", None),
                            "reason": f"Broker rejected: {comment} (code {retcode})"
                        },
                    )

            time.sleep(30)

    finally:
        store.log_event("shutdown")
        mt5a.shutdown()


if __name__ == "__main__":
    main()
