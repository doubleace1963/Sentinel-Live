"""
Partial Profit Manager
Monitors open positions and executes partial profit taking at 3R in conservative mode.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Tuple

import Live1.mt5_adapter as mt5a
from Live1.storage import JsonStore, LiveState


def _safe_float(x: Any) -> float:
    """Safely convert value to float."""
    try:
        return float(x)
    except Exception:
        return 0.0


def _safe_int(x: Any) -> int:
    """Safely convert value to int."""
    try:
        return int(x)
    except Exception:
        return 0


def _calculate_current_r(
    *,
    pos_type: int,
    entry_price: float,
    current_price: float,
    sl_distance: float,
) -> float:
    """
    Calculate current R multiple for a position.
    pos_type: 0=BUY, 1=SELL
    """
    if sl_distance <= 0:
        return 0.0
    
    if pos_type == 0:  # BUY position
        current_profit = current_price - entry_price
    else:  # SELL position
        current_profit = entry_price - current_price
    
    return current_profit / sl_distance


def check_and_execute_partials(
    *,
    store: JsonStore,
    state: LiveState,
    magic: int,
    trading_mode: str,
) -> LiveState:
    """
    Manage partial profit taking using TP-based approach for conservative mode.
    
    Conservative mode strategy:
    1. When new position detected -> Modify TP to 3R, store original TP
    2. When position reaches 3R -> Close 50%, move SL to breakeven, restore original TP
    
    Aggressive mode:
    - Do nothing, let positions run to full TP or SL
    
    Returns updated state.
    """
    # Skip if not in conservative mode
    if trading_mode.lower() != "conservative":
        return state
    
    # Get all open positions for our magic number
    positions = mt5a.positions_get_by_magic(magic)
    if not positions:
        return state
    
    # Clean up state for positions that no longer exist
    current_tickets = {_safe_int(getattr(p, "ticket", 0)) for p in positions if _safe_int(getattr(p, "ticket", 0)) > 0}
    
    # Cleanup partials_taken
    tickets_to_remove = [t for t in state.partials_taken.keys() if t not in current_tickets]
    if tickets_to_remove:
        for t in tickets_to_remove:
            del state.partials_taken[t]
        store.log_event("cleanup_closed_partials", {"removed_tickets": tickets_to_remove})
    
    # Cleanup positions_at_3r_tp
    tp_tickets_to_remove = [t for t in state.positions_at_3r_tp.keys() if t not in current_tickets]
    if tp_tickets_to_remove:
        for t in tp_tickets_to_remove:
            del state.positions_at_3r_tp[t]
        store.log_event("cleanup_3r_tp_positions", {"removed_tickets": tp_tickets_to_remove})
    
    if tickets_to_remove or tp_tickets_to_remove:
        store.save_state(state)
    
    # Process each position
    for pos in positions:
        try:
            ticket = _safe_int(getattr(pos, "ticket", 0))
            if ticket == 0:
                continue
            
            symbol = getattr(pos, "symbol", "")
            pos_type = _safe_int(getattr(pos, "type", -1))  # 0=BUY, 1=SELL
            entry_price = _safe_float(getattr(pos, "price_open", 0.0))
            current_sl = _safe_float(getattr(pos, "sl", 0.0))
            current_tp = _safe_float(getattr(pos, "tp", 0.0))
            volume = _safe_float(getattr(pos, "volume", 0.0))
            
            if not symbol or pos_type not in (0, 1) or entry_price == 0 or volume == 0:
                continue
            
            # STEP 1: Check if this is a new position that needs TP modified to 3R
            if ticket not in state.positions_at_3r_tp and ticket not in state.partials_taken:
                # Calculate 3R target
                sl_distance = abs(entry_price - current_sl)
                if sl_distance <= 0:
                    continue
                
                if pos_type == 0:  # BUY
                    three_r_tp = entry_price + (sl_distance * 3)
                else:  # SELL
                    three_r_tp = entry_price - (sl_distance * 3)
                
                # Only modify if current TP is beyond 3R (otherwise it's already at or below 3R)
                needs_modification = False
                if pos_type == 0:  # BUY
                    needs_modification = current_tp > three_r_tp
                else:  # SELL
                    needs_modification = current_tp < three_r_tp
                
                if needs_modification:
                    # Modify position to set TP at 3R
                    modify_result = mt5a.modify_position_sl_tp(
                        ticket=ticket,
                        symbol=symbol,
                        sl=current_sl,
                        tp=three_r_tp,
                        magic=magic,
                        comment="tp_to_3r",
                    )
                    
                    if modify_result is not None and getattr(modify_result, "retcode", None) == 10009:
                        # Successfully modified - store original TP
                        state.positions_at_3r_tp[ticket] = {
                            "symbol": symbol,
                            "original_tp": current_tp,
                            "three_r_tp": three_r_tp,
                            "entry_price": entry_price,
                            "original_sl": current_sl,
                            "modified_time": datetime.now().isoformat(timespec="seconds"),
                        }
                        store.save_state(state)
                        store.log_event(
                            "tp_modified_to_3r",
                            {
                                "ticket": ticket,
                                "symbol": symbol,
                                "original_tp": current_tp,
                                "new_tp_3r": three_r_tp,
                                "entry": entry_price,
                            }
                        )
                    else:
                        store.log_event(
                            "tp_modify_to_3r_failed",
                            {
                                "ticket": ticket,
                                "retcode": getattr(modify_result, "retcode", None) if modify_result else None,
                                "comment": getattr(modify_result, "comment", None) if modify_result else "None",
                            }
                        )
            
            # STEP 2: Check if position is at/near 3R and needs partial taken
            elif ticket in state.positions_at_3r_tp and ticket not in state.partials_taken:
                position_info = state.positions_at_3r_tp[ticket]
                three_r_tp = position_info["three_r_tp"]
                original_tp = position_info["original_tp"]
                original_sl = position_info["original_sl"]
                
                # Get current market price
                tick = mt5a.get_tick(symbol)
                if tick is None:
                    continue
                
                current_price = tick.bid if pos_type == 0 else tick.ask
                
                # Calculate current R
                sl_distance = abs(entry_price - original_sl)
                current_r = _calculate_current_r(
                    pos_type=pos_type,
                    entry_price=entry_price,
                    current_price=current_price,
                    sl_distance=sl_distance,
                )
                
                # Check if we're at or past 3R
                if current_r >= 2.95:  # Slightly before 3R to catch it
                    # Get symbol info for volume precision
                    symbol_info = mt5a.get_symbol_info(symbol)
                    if symbol_info is None:
                        continue
                    
                    volume_step = _safe_float(getattr(symbol_info, "volume_step", 0.01))
                    volume_min = _safe_float(getattr(symbol_info, "volume_min", 0.01))
                    
                    # Calculate partial volume (50%)
                    partial_volume = volume / 2
                    if volume_step > 0:
                        partial_volume = round(partial_volume / volume_step) * volume_step
                    else:
                        partial_volume = round(partial_volume, 2)
                    
                    if partial_volume < volume_min or partial_volume >= volume:
                        store.log_event(
                            "partial_volume_invalid",
                            {"ticket": ticket, "volume": volume, "partial_volume": partial_volume}
                        )
                        continue
                    
                    # Close 50% of the position
                    close_result = mt5a.close_position_partial(
                        ticket=ticket,
                        symbol=symbol,
                        volume=partial_volume,
                        magic=magic,
                        comment="partial_3r",
                    )
                    
                    if close_result is None or getattr(close_result, "retcode", None) != 10009:
                        store.log_event(
                            "partial_close_failed",
                            {
                                "ticket": ticket,
                                "retcode": getattr(close_result, "retcode", None) if close_result else None,
                                "comment": getattr(close_result, "comment", None) if close_result else None,
                            }
                        )
                        continue
                    
                    store.log_event(
                        "partial_close_success",
                        {
                            "ticket": ticket,
                            "symbol": symbol,
                            "volume_closed": partial_volume,
                            "volume_remaining": volume - partial_volume,
                            "current_r": round(current_r, 2),
                        }
                    )
                    
                    # Now restore original TP and move SL to breakeven
                    modify_result = mt5a.modify_position_sl_tp(
                        ticket=ticket,
                        symbol=symbol,
                        sl=entry_price,  # Move to breakeven
                        tp=original_tp,  # Restore original TP
                        magic=magic,
                        comment="restore_tp_be_sl",
                    )
                    
                    if modify_result is not None and getattr(modify_result, "retcode", None) == 10009:
                        store.log_event(
                            "tp_restored_sl_to_be",
                            {
                                "ticket": ticket,
                                "symbol": symbol,
                                "new_sl": entry_price,
                                "restored_tp": original_tp,
                            }
                        )
                    else:
                        store.log_event(
                            "tp_restore_failed",
                            {
                                "ticket": ticket,
                                "retcode": getattr(modify_result, "retcode", None) if modify_result else None,
                            }
                        )
                    
                    # Mark as partial taken and remove from 3r_tp tracking
                    state.partials_taken[ticket] = {
                        "symbol": symbol,
                        "entry_price": entry_price,
                        "original_sl": original_sl,
                        "new_sl": entry_price,
                        "tp": original_tp,
                        "partial_time": datetime.now().isoformat(timespec="seconds"),
                        "r_at_partial": round(current_r, 2),
                        "volume_closed": partial_volume,
                        "volume_remaining": volume - partial_volume,
                    }
                    
                    # Remove from 3r_tp tracking
                    if ticket in state.positions_at_3r_tp:
                        del state.positions_at_3r_tp[ticket]
                    
                    store.save_state(state)
        
        except Exception as e:
            store.log_event(
                "partial_execution_error",
                {
                    "ticket": ticket if 'ticket' in locals() else 'unknown',
                    "error": str(e),
                    "error_type": type(e).__name__,
                }
            )
            continue
    
    return state
