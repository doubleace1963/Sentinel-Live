from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Set, Tuple

import Live1.mt5_adapter as mt5a
from Live1.storage import JsonStore, LiveState


@dataclass
class RuntimeTracker:
    known_order_tickets: Set[int]
    known_position_tickets: Set[int]


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _safe_int(x: Any) -> int:
    try:
        return int(x)
    except Exception:
        return 0


def reconcile(
    *,
    store: JsonStore,
    state: LiveState,
    tracker: RuntimeTracker,
    magic: int,
    cancel_expired: bool,
) -> Tuple[LiveState, RuntimeTracker]:
    """Poll MT5 and log changes.

    - Logs pending orders appearing/disappearing.
    - Logs positions opening/closing.
    - Logs MT5 deal history incrementally (fills/closures).
    """

    # 1) Pending orders
    orders = mt5a.orders_get_by_magic(magic)
    current_orders: Dict[int, Any] = { _safe_int(getattr(o, "ticket", 0)): o for o in orders }
    current_order_tickets = {t for t in current_orders.keys() if t > 0}

    new_orders = current_order_tickets - tracker.known_order_tickets
    gone_orders = tracker.known_order_tickets - current_order_tickets

    for t in sorted(new_orders):
        o = current_orders.get(t)
        store.log_event(
            "pending_order_seen",
            {
                "ticket": t,
                "symbol": getattr(o, "symbol", None),
                "type": getattr(o, "type", None),
                "price_open": getattr(o, "price_open", None),
                "sl": getattr(o, "sl", None),
                "tp": getattr(o, "tp", None),
                "time_setup": getattr(o, "time_setup", None),
                "time_expiration": getattr(o, "time_expiration", None),
            },
        )

    for t in sorted(gone_orders):
        store.log_event("pending_order_gone", {"ticket": t})

    tracker.known_order_tickets = current_order_tickets

    # Optional: cancel expired orders ourselves (in addition to broker expiration)
    if cancel_expired:
        now = datetime.now()
        for t, o in current_orders.items():
            exp = getattr(o, "time_expiration", 0) or 0
            if exp and isinstance(exp, (int, float)):
                exp_dt = datetime.fromtimestamp(int(exp))
                if now >= exp_dt:
                    res = mt5a.cancel_order(t, magic=magic, comment="expired")
                    store.log_event(
                        "pending_order_cancel_attempt",
                        {"ticket": t, "result": getattr(res, "retcode", None), "comment": getattr(res, "comment", None)},
                    )

    # 2) Positions
    positions = mt5a.positions_get_by_magic(magic)
    current_positions: Dict[int, Any] = { _safe_int(getattr(p, "ticket", 0)): p for p in positions }
    current_pos_tickets = {t for t in current_positions.keys() if t > 0}

    new_pos = current_pos_tickets - tracker.known_position_tickets
    gone_pos = tracker.known_position_tickets - current_pos_tickets

    for t in sorted(new_pos):
        p = current_positions.get(t)
        store.log_event(
            "position_open_seen",
            {
                "ticket": t,
                "symbol": getattr(p, "symbol", None),
                "type": getattr(p, "type", None),
                "volume": getattr(p, "volume", None),
                "price_open": getattr(p, "price_open", None),
                "sl": getattr(p, "sl", None),
                "tp": getattr(p, "tp", None),
                "profit": getattr(p, "profit", None),
            },
        )

    for t in sorted(gone_pos):
        store.log_event("position_gone", {"ticket": t})

    tracker.known_position_tickets = current_pos_tickets

    # 3) Deal history (incremental)
    now = datetime.now()
    if state.last_deal_poll:
        try:
            start = datetime.fromisoformat(state.last_deal_poll)
        except Exception:
            start = now - timedelta(hours=12)
    else:
        start = now - timedelta(hours=12)

    deals = mt5a.history_deals_get(start, now)
    if deals:
        for d in deals:
            if _safe_int(getattr(d, "magic", 0)) != int(magic):
                continue
            store.log_event(
                "deal",
                {
                    "ticket": getattr(d, "ticket", None),
                    "order": getattr(d, "order", None),
                    "position_id": getattr(d, "position_id", None),
                    "symbol": getattr(d, "symbol", None),
                    "type": getattr(d, "type", None),
                    "entry": getattr(d, "entry", None),
                    "volume": getattr(d, "volume", None),
                    "price": getattr(d, "price", None),
                    "profit": getattr(d, "profit", None),
                    "time": getattr(d, "time", None),
                    "comment": getattr(d, "comment", None),
                },
            )

    state.last_deal_poll = _iso(now)
    store.save_state(state)

    return state, tracker
