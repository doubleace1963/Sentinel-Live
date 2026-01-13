from __future__ import annotations

import json
import queue
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import tkinter as tk
from tkinter import ttk

# Ensure Live1 package is importable (needed when running from Live1 directory)
try:
    import Live1.config
except ModuleNotFoundError:
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

try:
    from Live1.config import CONFIG
    import Live1.mt5_adapter as mt5a

    _MT5_AVAILABLE = True
except Exception:
    CONFIG = None  # type: ignore[assignment]
    mt5a = None  # type: ignore[assignment]
    _MT5_AVAILABLE = False


@dataclass
class _ProcState:
    process: subprocess.Popen[str]
    started_at: float


@dataclass(frozen=True)
class _Event:
    time: str
    type: str
    payload: dict[str, Any]


class Live1Gui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Live1 — Live Trading (GUI)")
        self.geometry("1100x720")

        self._root_dir = Path(__file__).resolve().parents[1]
        self._live_dir = self._root_dir / "Live1"
        self._events_path = self._live_dir / "events.jsonl"
        self._state_path = self._live_dir / "state.json"

        self._proc: Optional[_ProcState] = None
        self._stdout_thread: Optional[threading.Thread] = None
        self._stdout_queue: "queue.Queue[str]" = queue.Queue()
        self._events_offset: int = 0

        self._events_loaded_count: int = 0
        self._max_event_rows: int = 2000

        self._symbol_iids: dict[str, str] = {}
        self._last_event_time: str | None = None
        self._weekend_mode: bool = False

        self._mt5_ready: bool = False
        self._mt5_last_error: str | None = None

        self._build_ui()
        self._set_running(False)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # periodic UI updates
        self.after(250, self._poll_stdout_queue)
        self.after(500, self._tail_events)
        self.after(1000, self._refresh_status)
        self.after(1500, self._refresh_mt5_counts)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)

        top = ttk.Frame(outer)
        top.pack(fill="x")

        self._status_var = tk.StringVar(value="Status: stopped")
        self._state_var = tk.StringVar(value="State: (no data yet)")
        self._mt5_var = tk.StringVar(value="MT5: (unknown)")
        self._counts_var = tk.StringVar(value="Counts: (n/a)")
        self._mode_var = tk.StringVar(value="Mode: (loading...)")

        self._btn_start = ttk.Button(top, text="Start Live1", command=self._start)
        self._btn_stop = ttk.Button(top, text="Stop Live1", command=self._stop)
        self._btn_load_recent = ttk.Button(top, text="Load recent events", command=self._load_recent_events)
        self._btn_clear = ttk.Button(top, text="Clear view", command=self._clear_views)

        self._btn_start.pack(side="left")
        self._btn_stop.pack(side="left", padx=(8, 0))
        self._btn_load_recent.pack(side="left", padx=(16, 0))
        self._btn_clear.pack(side="left", padx=(8, 0))

        ttk.Label(top, textvariable=self._status_var).pack(side="left", padx=(16, 0))

        info = ttk.Frame(outer)
        info.pack(fill="x", pady=(8, 8))
        ttk.Label(info, textvariable=self._state_var).pack(fill="x")
        ttk.Label(info, textvariable=self._mt5_var).pack(fill="x")
        ttk.Label(info, textvariable=self._counts_var).pack(fill="x")
        ttk.Label(info, textvariable=self._mode_var).pack(fill="x")

        self._tabs = ttk.Notebook(outer)
        self._tabs.pack(fill="both", expand=True)

        # Dashboard tab
        dash = ttk.Frame(self._tabs, padding=6)
        self._tabs.add(dash, text="Dashboard")

        self._dash_tree = ttk.Treeview(
            dash,
            columns=(
                "symbol",
                "last_time",
                "last_type",
                "last_action",
                "entry",
                "sl",
                "tp",
                "volume",
                "est_r",
                "retcode",
            ),
            show="headings",
            height=18,
        )
        for col, w in (
            ("symbol", 120),
            ("last_time", 160),
            ("last_type", 160),
            ("last_action", 220),
            ("entry", 90),
            ("sl", 90),
            ("tp", 90),
            ("volume", 80),
            ("est_r", 70),
            ("retcode", 80),
        ):
            self._dash_tree.heading(col, text=col)
            self._dash_tree.column(col, width=w, anchor="w")

        dash_y = ttk.Scrollbar(dash, orient="vertical", command=self._dash_tree.yview)
        dash_x = ttk.Scrollbar(dash, orient="horizontal", command=self._dash_tree.xview)
        self._dash_tree.configure(yscrollcommand=dash_y.set, xscrollcommand=dash_x.set)

        self._dash_tree.grid(row=0, column=0, sticky="nsew")
        dash_y.grid(row=0, column=1, sticky="ns")
        dash_x.grid(row=1, column=0, sticky="ew")
        dash.rowconfigure(0, weight=1)
        dash.columnconfigure(0, weight=1)

        # Events tab (structured)
        events = ttk.Frame(self._tabs, padding=6)
        self._tabs.add(events, text="Events")

        self._events_tree = ttk.Treeview(
            events,
            columns=("time", "type", "symbol", "summary"),
            show="headings",
            height=14,
        )
        for col, w in (("time", 170), ("type", 200), ("symbol", 120), ("summary", 520)):
            self._events_tree.heading(col, text=col)
            self._events_tree.column(col, width=w, anchor="w")

        ev_y = ttk.Scrollbar(events, orient="vertical", command=self._events_tree.yview)
        ev_x = ttk.Scrollbar(events, orient="horizontal", command=self._events_tree.xview)
        self._events_tree.configure(yscrollcommand=ev_y.set, xscrollcommand=ev_x.set)

        self._events_tree.grid(row=0, column=0, sticky="nsew")
        ev_y.grid(row=0, column=1, sticky="ns")
        ev_x.grid(row=1, column=0, sticky="ew")

        self._payload_text = tk.Text(events, height=10, wrap="none")
        self._payload_text.configure(state="disabled")
        payload_y = ttk.Scrollbar(events, orient="vertical", command=self._payload_text.yview)
        self._payload_text.configure(yscrollcommand=payload_y.set)

        self._payload_text.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        payload_y.grid(row=2, column=1, sticky="ns", pady=(8, 0))

        events.rowconfigure(0, weight=2)
        events.rowconfigure(2, weight=1)
        events.columnconfigure(0, weight=1)

        self._events_tree.bind("<<TreeviewSelect>>", self._on_event_select)

        # Output tab (raw stdout + GUI messages)
        output = ttk.Frame(self._tabs, padding=6)
        self._tabs.add(output, text="Output")

        self._output_text = tk.Text(output, wrap="none")
        self._output_text.configure(state="disabled")

        out_y = ttk.Scrollbar(output, orient="vertical", command=self._output_text.yview)
        out_x = ttk.Scrollbar(output, orient="horizontal", command=self._output_text.xview)
        self._output_text.configure(yscrollcommand=out_y.set, xscrollcommand=out_x.set)

        self._output_text.grid(row=0, column=0, sticky="nsew")
        out_y.grid(row=0, column=1, sticky="ns")
        out_x.grid(row=1, column=0, sticky="ew")

        output.rowconfigure(0, weight=1)
        output.columnconfigure(0, weight=1)

        hint = (
            "Dashboard shows per-symbol status derived from events.\n"
            "Events shows a structured table + payload viewer. Output shows raw stdout/errors."
        )
        ttk.Label(outer, text=hint).pack(fill="x", pady=(8, 0))

    def _append_output(self, line: str) -> None:
        self._output_text.configure(state="normal")
        self._output_text.insert("end", line + "\n")
        self._output_text.see("end")
        self._output_text.configure(state="disabled")

    def _set_running(self, running: bool) -> None:
        if running:
            self._btn_start.configure(state="disabled")
            self._btn_stop.configure(state="normal")
            self._status_var.set("Status: running")
        else:
            self._btn_start.configure(state="normal")
            self._btn_stop.configure(state="disabled")
            self._status_var.set("Status: stopped")

    def _start(self) -> None:
        if self._proc is not None:
            return

        self._live_dir.mkdir(parents=True, exist_ok=True)
        if not self._events_path.exists():
            self._events_path.write_text("", encoding="utf-8")
        self._events_offset = self._events_path.stat().st_size

        cmd = [sys.executable, str(self._live_dir / "app.py")]

        try:
            # New process group lets us send CTRL_BREAK_EVENT on Windows.
            creationflags = 0
            if sys.platform.startswith("win"):
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

            p = subprocess.Popen(
                cmd,
                cwd=str(self._root_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=creationflags,
            )
        except Exception as e:
            self._append_output(f"[GUI] Failed to start: {e}")
            self._set_running(False)
            return

        self._proc = _ProcState(process=p, started_at=time.time())
        self._set_running(True)
        self._append_output(f"[GUI] Started: {' '.join(cmd)}")

        self._stdout_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self._stdout_thread.start()

    def _read_stdout(self) -> None:
        proc_state = self._proc
        if proc_state is None:
            return
        p = proc_state.process
        if p.stdout is None:
            return

        for raw in p.stdout:
            line = raw.rstrip("\n")
            if line:
                self._stdout_queue.put(f"[STDOUT] {line}")

    def _stop(self) -> None:
        proc_state = self._proc
        if proc_state is None:
            return

        p = proc_state.process
        self._append_output("[GUI] Stopping…")

        # Try graceful stop first.
        try:
            if sys.platform.startswith("win"):
                p.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
            else:
                p.send_signal(signal.SIGINT)
        except Exception:
            pass

        try:
            p.wait(timeout=5)
        except Exception:
            try:
                p.terminate()
            except Exception:
                pass

        self._proc = None
        self._set_running(False)
        self._append_output("[GUI] Stopped")

    def _on_close(self) -> None:
        try:
            self._stop()
        finally:
            if _MT5_AVAILABLE and self._mt5_ready:
                try:
                    mt5a.shutdown()  # type: ignore[misc]
                except Exception:
                    pass
            self.destroy()

    def _poll_stdout_queue(self) -> None:
        while True:
            try:
                msg = self._stdout_queue.get_nowait()
            except queue.Empty:
                break
            self._append_output(msg)

        self.after(250, self._poll_stdout_queue)

    def _tail_events(self) -> None:
        try:
            if self._events_path.exists():
                with self._events_path.open("r", encoding="utf-8") as f:
                    f.seek(self._events_offset)
                    for raw in f:
                        raw = raw.strip()
                        if not raw:
                            continue
                        try:
                            row = json.loads(raw)
                            ev = _Event(
                                time=str(row.get("time", "?")),
                                type=str(row.get("type", "?")),
                                payload=dict(row.get("payload", {}) or {}),
                            )
                            self._handle_event(ev)
                        except Exception:
                            self._append_output(f"[EVENT] {raw}")
                    self._events_offset = f.tell()
        except Exception as e:
            self._append_output(f"[GUI] Event tail error: {e}")

        self.after(500, self._tail_events)

    def _refresh_status(self) -> None:
        # Update state line (best-effort).
        try:
            if self._state_path.exists():
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
                last_d1_start = data.get("last_d1_start", {}) or {}
                symbols_tracked = len(last_d1_start)
                saved_at = data.get("saved_at")
                self._state_var.set(f"State: {symbols_tracked} symbols tracked; saved_at={saved_at}")
            else:
                self._state_var.set("State: (no state.json yet)")
        except Exception:
            self._state_var.set("State: (unreadable state.json)")
        
        # Update trading mode display
        try:
            if CONFIG is not None:
                mode = getattr(CONFIG, "trading_mode", "conservative").upper()
                if mode == "CONSERVATIVE":
                    self._mode_var.set("Mode: CONSERVATIVE (50% partial at 3R, SL to breakeven)")
                elif mode == "AGGRESSIVE":
                    self._mode_var.set("Mode: AGGRESSIVE (no partials, full position to TP/SL)")
                else:
                    self._mode_var.set(f"Mode: {mode}")
            else:
                self._mode_var.set("Mode: (config not loaded)")
        except Exception:
            self._mode_var.set("Mode: (error reading config)")

        # If process exited, reflect it.
        if self._proc is not None:
            p = self._proc.process
            rc = p.poll()
            if rc is not None:
                self._append_output(f"[GUI] Live1 exited with code {rc}")
                self._proc = None
                self._set_running(False)

        self.after(1000, self._refresh_status)

    def _refresh_mt5_counts(self) -> None:
        if not _MT5_AVAILABLE:
            self._mt5_var.set("MT5: adapter not available")
            self._counts_var.set("Counts: (n/a)")
            self.after(5000, self._refresh_mt5_counts)
            return

        # Initialize MT5 once (best-effort). This is only for *display*.
        if not self._mt5_ready:
            try:
                self._mt5_ready = bool(mt5a.initialize())  # type: ignore[misc]
                if not self._mt5_ready:
                    self._mt5_last_error = "initialize failed"
            except Exception as e:
                self._mt5_ready = False
                self._mt5_last_error = str(e)

        if not self._mt5_ready:
            self._mt5_var.set(f"MT5: not connected ({self._mt5_last_error})")
            self._counts_var.set("Counts: (n/a)")
            self.after(5000, self._refresh_mt5_counts)
            return

        try:
            magic = int(getattr(CONFIG, "magic_number", 0) or 0)  # type: ignore[arg-type]
            orders = mt5a.orders_get_by_magic(magic)  # type: ignore[misc]
            positions = mt5a.positions_get_by_magic(magic)  # type: ignore[misc]
            self._mt5_var.set("MT5: connected")
            self._counts_var.set(
                "Counts: "
                f"pending_orders={len(orders)}; positions={len(positions)}; "
                f"weekend_mode={self._weekend_mode}; last_event={self._last_event_time}"
            )
        except Exception as e:
            self._mt5_var.set(f"MT5: connected (read error: {e})")

        self.after(1500, self._refresh_mt5_counts)

    def _handle_event(self, ev: _Event) -> None:
        self._last_event_time = ev.time
        if ev.type == "weekend_mode":
            self._weekend_mode = True
        if ev.type == "startup":
            self._weekend_mode = False

        symbol = self._event_symbol(ev)
        summary = self._event_summary(ev)

        # Add to structured events table
        iid = f"e{self._events_loaded_count}"
        self._events_loaded_count += 1
        self._events_tree.insert("", "end", iid=iid, values=(ev.time, ev.type, symbol or "", summary))

        # Trim table (keep GUI responsive)
        children = self._events_tree.get_children("")
        if len(children) > self._max_event_rows:
            for old in children[: max(0, len(children) - self._max_event_rows)]:
                self._events_tree.delete(old)

        # Update dashboard per symbol
        if symbol:
            self._update_symbol_dashboard(symbol, ev)

    def _event_symbol(self, ev: _Event) -> str | None:
        p = ev.payload
        sym = p.get("symbol")
        if isinstance(sym, str) and sym:
            return sym
        return None

    def _event_summary(self, ev: _Event) -> str:
        p = ev.payload
        t = ev.type
        try:
            if t == "new_day":
                return f"d1_start={p.get('d1_start')}"
            if t == "no_setup":
                return "no valid setup"
            if t == "placing_order":
                return (
                    f"{p.get('fvg_type')} entry_adj={p.get('entry_adj')} vol={p.get('volume')} "
                    f"sl={p.get('sl')} tp={p.get('tp')} est_r={p.get('est_r')}"
                )
            if t == "order_send_result":
                return f"retcode={p.get('retcode')} order={p.get('order')} deal={p.get('deal')}"
            if t.startswith("skip_"):
                # Keep it short
                return json.dumps(p, ensure_ascii=False, separators=(",", ":"))[:180]
            if t == "pending_order_seen":
                return f"ticket={p.get('ticket')} price_open={p.get('price_open')}"
            if t == "position_open_seen":
                return f"ticket={p.get('ticket')} price_open={p.get('price_open')} profit={p.get('profit')}"
            if t == "deal":
                return f"pos={p.get('position_id')} price={p.get('price')} profit={p.get('profit')} entry={p.get('entry')}"
            return json.dumps(p, ensure_ascii=False, separators=(",", ":"))[:180]
        except Exception:
            return "(unreadable payload)"

    def _update_symbol_dashboard(self, symbol: str, ev: _Event) -> None:
        p = ev.payload
        iid = self._symbol_iids.get(symbol)
        if iid is None:
            iid = f"s:{symbol}"
            self._symbol_iids[symbol] = iid
            self._dash_tree.insert(
                "",
                "end",
                iid=iid,
                values=(symbol, "", "", "", "", "", "", "", "", ""),
            )

        last_action = ""
        entry = ""
        sl = ""
        tp = ""
        volume = ""
        est_r = ""
        retcode = ""

        if ev.type in ("placing_order", "skip_duplicate", "skip_invalid_buy_limit", "skip_invalid_sell_limit"):
            last_action = ev.type
        elif ev.type in ("order_send_result", "order_send_failed"):
            last_action = ev.type
        elif ev.type in ("no_setup", "new_day"):
            last_action = ev.type
        elif ev.type == "deal":
            last_action = "deal"

        if ev.type == "placing_order":
            entry = str(p.get("entry_adj", ""))
            sl = str(p.get("sl", ""))
            tp = str(p.get("tp", ""))
            volume = str(p.get("volume", ""))
            est_r = str(p.get("est_r", ""))
        if ev.type == "order_send_result":
            retcode_val = p.get("retcode", "")
            # Only show successful orders (10009 = Request executed)
            # Ignore failed orders (10018 = Market closed, etc.)
            if retcode_val == 10009:
                retcode = str(retcode_val)
            else:
                # Failed order - don't update display, treat as order_send_failed
                last_action = "order_send_failed"
                retcode = str(retcode_val)

        # Persist existing row values where we don't have new info.
        old = self._dash_tree.item(iid, "values")
        old_map = {
            "symbol": old[0],
            "last_time": old[1],
            "last_type": old[2],
            "last_action": old[3],
            "entry": old[4],
            "sl": old[5],
            "tp": old[6],
            "volume": old[7],
            "est_r": old[8],
            "retcode": old[9],
        }

        new_vals = (
            symbol,
            ev.time,
            ev.type,
            last_action or old_map["last_action"],
            entry or old_map["entry"],
            sl or old_map["sl"],
            tp or old_map["tp"],
            volume or old_map["volume"],
            est_r or old_map["est_r"],
            retcode or old_map["retcode"],
        )
        self._dash_tree.item(iid, values=new_vals)

    def _on_event_select(self, _event: object) -> None:
        sel = self._events_tree.selection()
        if not sel:
            return
        iid = sel[0]
        vals = self._events_tree.item(iid, "values")
        if not vals or len(vals) < 4:
            return

        # Best-effort: re-load the JSON payload by searching near the end of the file.
        # If that fails, show just the summary row.
        time_val, type_val, symbol_val, summary_val = vals
        payload_text = f"time: {time_val}\ntype: {type_val}\nsymbol: {symbol_val}\nsummary: {summary_val}\n"
        self._payload_text.configure(state="normal")
        self._payload_text.delete("1.0", "end")
        self._payload_text.insert("end", payload_text)
        self._payload_text.configure(state="disabled")

    def _load_recent_events(self, max_lines: int = 250) -> None:
        if not self._events_path.exists():
            self._append_output("[GUI] No events.jsonl yet")
            return

        try:
            lines = self._events_path.read_text(encoding="utf-8").splitlines()
            tail = lines[-max_lines:]
            for raw in tail:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    row = json.loads(raw)
                    ev = _Event(
                        time=str(row.get("time", "?")),
                        type=str(row.get("type", "?")),
                        payload=dict(row.get("payload", {}) or {}),
                    )
                    self._handle_event(ev)
                except Exception:
                    continue
            self._append_output(f"[GUI] Loaded recent {len(tail)} event lines")
        except Exception as e:
            self._append_output(f"[GUI] Failed loading recent events: {e}")

    def _clear_views(self) -> None:
        for iid in self._events_tree.get_children(""):
            self._events_tree.delete(iid)
        for iid in self._dash_tree.get_children(""):
            self._dash_tree.delete(iid)
        self._symbol_iids.clear()
        self._events_loaded_count = 0
        self._last_event_time = None
        self._weekend_mode = False
        self._payload_text.configure(state="normal")
        self._payload_text.delete("1.0", "end")
        self._payload_text.configure(state="disabled")
        self._append_output("[GUI] Cleared view")


def main() -> None:
    app = Live1Gui()
    app.mainloop()


if __name__ == "__main__":
    main()
