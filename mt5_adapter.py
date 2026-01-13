from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import MetaTrader5 as mt5
import pandas as pd


@dataclass(frozen=True)
class Tick:
    time: datetime
    bid: float
    ask: float


def initialize() -> bool:
    return bool(mt5.initialize())


def shutdown() -> None:
    try:
        mt5.shutdown()
    except Exception:
        pass


def ensure_symbol(symbol: str) -> bool:
    info = mt5.symbol_info(symbol)
    if info is None:
        return False
    if not info.visible:
        return bool(mt5.symbol_select(symbol, True))
    return True


def get_forex_symbols() -> list[str]:
    symbols = mt5.symbols_get()
    if not symbols:
        return []

    # Keep consistent with your Demo1 heuristic.
    out: list[str] = []
    for s in symbols:
        path = getattr(s, "path", "") or ""
        name = getattr(s, "name", "") or ""
        if "FX" in path or name.endswith("FX"):
            out.append(name)
    return out


def fetch_daily(symbol: str, bars: int = 10) -> Optional[pd.DataFrame]:
    try:
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, bars)
        if rates is None or len(rates) == 0:
            return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        return df.sort_values("time").reset_index(drop=True)
    except Exception:
        return None


def fetch_m5(symbol: str, start: datetime, end: datetime) -> Optional[pd.DataFrame]:
    try:
        rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M5, start, end)
        if rates is None or len(rates) == 0:
            return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        return df.sort_values("time").reset_index(drop=True)
    except Exception:
        return None


def get_tick(symbol: str) -> Optional[Tick]:
    t = mt5.symbol_info_tick(symbol)
    if t is None:
        return None
    # MT5 tick times are epoch seconds.
    return Tick(time=datetime.fromtimestamp(t.time), bid=float(t.bid), ask=float(t.ask))


def get_spread_price(symbol: str) -> Optional[float]:
    tick = get_tick(symbol)
    if tick is None:
        return None
    return max(0.0, float(tick.ask) - float(tick.bid))


def get_symbol_info(symbol: str) -> Any:
    return mt5.symbol_info(symbol)


def account_info() -> Any:
    return mt5.account_info()


def place_limit_order(
    *,
    symbol: str,
    side: str,  # 'buy' | 'sell'
    volume: float,
    price: float,
    sl: float,
    tp: float,
    deviation_points: int,
    magic: int,
    comment: str,
    expiration: Optional[datetime] = None,
) -> Any:
    if side not in ("buy", "sell"):
        raise ValueError("side must be 'buy' or 'sell'")

    if not ensure_symbol(symbol):
        return None

    order_type = mt5.ORDER_TYPE_BUY_LIMIT if side == "buy" else mt5.ORDER_TYPE_SELL_LIMIT

    request: dict[str, Any] = {
        "action": mt5.TRADE_ACTION_PENDING,
        "symbol": symbol,
        "volume": float(volume),
        "type": order_type,
        "price": float(price),
        "sl": float(sl),
        "tp": float(tp),
        "deviation": int(deviation_points),
        "magic": int(magic),
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_RETURN,
    }

    if expiration is not None:
        request["type_time"] = mt5.ORDER_TIME_SPECIFIED
        request["expiration"] = int(expiration.timestamp())

    return mt5.order_send(request)


def orders_get(magic: Optional[int] = None):
    if magic is None:
        return mt5.orders_get()
    return mt5.orders_get(group="*", ticket=0) if False else mt5.orders_get()  # group not reliable across brokers


def positions_get():
    return mt5.positions_get()


def cancel_order(ticket: int, magic: int, comment: str = "cancel") -> Any:
    req = {
        "action": mt5.TRADE_ACTION_REMOVE,
        "order": int(ticket),
        "magic": int(magic),
        "comment": comment,
    }
    return mt5.order_send(req)


def orders_get_by_magic(magic: int):
    """Return pending orders filtered by magic (best-effort; some brokers ignore server-side filters)."""
    orders = mt5.orders_get()
    if not orders:
        return []
    out = []
    for o in orders:
        if int(getattr(o, "magic", 0) or 0) == int(magic):
            out.append(o)
    return out


def positions_get_by_magic(magic: int):
    positions = mt5.positions_get()
    if not positions:
        return []
    out = []
    for p in positions:
        if int(getattr(p, "magic", 0) or 0) == int(magic):
            out.append(p)
    return out


def history_deals_get(start: datetime, end: datetime):
    """Fetch deals in [start, end]. Useful for logging fills and closes."""
    try:
        return mt5.history_deals_get(start, end)
    except Exception:
        return None


def modify_position_sl_tp(ticket: int, symbol: str, sl: float, tp: float, magic: int, comment: str = "modify") -> Any:
    """Modify stop loss and take profit for an existing position."""
    if not ensure_symbol(symbol):
        return None
    
    request: dict[str, Any] = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": int(ticket),
        "symbol": symbol,
        "sl": float(sl),
        "tp": float(tp),
        "magic": int(magic),
        "comment": comment,
    }
    
    return mt5.order_send(request)


def close_position_partial(ticket: int, symbol: str, volume: float, magic: int, comment: str = "partial") -> Any:
    """Close a partial amount of a position."""
    if not ensure_symbol(symbol):
        return None
    
    # Get position info to determine type (buy/sell)
    positions = mt5.positions_get(ticket=ticket)
    if not positions or len(positions) == 0:
        return None
    
    pos = positions[0]
    pos_type = int(getattr(pos, "type", -1) or -1)  # 0=BUY, 1=SELL
    
    # Get current tick to determine closing price
    tick = get_tick(symbol)
    if tick is None:
        return None
    
    # To close a BUY position, we SELL at bid. To close SELL position, we BUY at ask.
    if pos_type == 0:  # BUY position
        order_type = mt5.ORDER_TYPE_SELL
        price = tick.bid
    elif pos_type == 1:  # SELL position
        order_type = mt5.ORDER_TYPE_BUY
        price = tick.ask
    else:
        return None
    
    request: dict[str, Any] = {
        "action": mt5.TRADE_ACTION_DEAL,
        "position": int(ticket),
        "symbol": symbol,
        "volume": float(volume),
        "type": order_type,
        "price": float(price),
        "deviation": 20,  # Acceptable slippage in points
        "magic": int(magic),
        "comment": comment,
        "type_filling": mt5.ORDER_FILLING_RETURN,
    }
    
    return mt5.order_send(request)
