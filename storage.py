import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class LiveState:
    # Tracks last seen D1 candle start per symbol (ISO string)
    last_d1_start: Dict[str, str]

    # Tracks symbols where orders were successfully placed for current day (symbol -> d1_start)
    # Used to prevent re-placing orders after they fill and close
    orders_placed: Dict[str, str]

    # Tracks positions that have had partial profits taken (position_ticket -> dict with metadata)
    # Format: {ticket: {"entry_price": float, "sl": float, "tp": float, "partial_time": str}}
    partials_taken: Dict[int, Dict[str, Any]]

    # Tracks positions with TP modified to 3R (position_ticket -> original TP)
    # Format: {ticket: {"original_tp": float, "three_r_tp": float, "entry": float, "sl": float}}
    positions_at_3r_tp: Dict[int, Dict[str, Any]]

    # Tracks last time we polled deal history (ISO string)
    last_deal_poll: str | None = None

    # Tracks last date we logged weekend mode (YYYY-MM-DD)
    last_weekend_notice: str | None = None


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class JsonStore:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.base_dir / "state.json"
        self.events_path = self.base_dir / "events.jsonl"

    def load_state(self) -> LiveState:
        if not self.state_path.exists():
            return LiveState(last_d1_start={}, orders_placed={}, partials_taken={}, positions_at_3r_tp={}, last_deal_poll=None, last_weekend_notice=None)
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            # Convert partials_taken keys from string back to int
            partials_data = data.get("partials_taken", {})
            partials_taken = {int(k): v for k, v in partials_data.items()} if partials_data else {}
            
            # Convert positions_at_3r_tp keys from string back to int
            positions_3r_data = data.get("positions_at_3r_tp", {})
            positions_at_3r_tp = {int(k): v for k, v in positions_3r_data.items()} if positions_3r_data else {}
            
            return LiveState(
                last_d1_start=dict(data.get("last_d1_start", {})),
                orders_placed=dict(data.get("orders_placed", {})),
                partials_taken=partials_taken,
                positions_at_3r_tp=positions_at_3r_tp,
                last_deal_poll=data.get("last_deal_poll"),
                last_weekend_notice=data.get("last_weekend_notice"),
            )
        except Exception:
            return LiveState(last_d1_start={}, orders_placed={}, partials_taken={}, positions_at_3r_tp={}, last_deal_poll=None, last_weekend_notice=None)

    def save_state(self, state: LiveState) -> None:
        payload = asdict(state)
        # Convert partials_taken int keys to strings for JSON serialization
        if "partials_taken" in payload and payload["partials_taken"]:
            payload["partials_taken"] = {str(k): v for k, v in payload["partials_taken"].items()}
        # Convert positions_at_3r_tp int keys to strings for JSON serialization
        if "positions_at_3r_tp" in payload and payload["positions_at_3r_tp"]:
            payload["positions_at_3r_tp"] = {str(k): v for k, v in payload["positions_at_3r_tp"].items()}
        payload["saved_at"] = _now_iso()
        self.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def log_event(self, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
        row = {
            "time": _now_iso(),
            "type": event_type,
            "payload": payload or {},
        }
        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
