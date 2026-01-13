# Live1 (Live Trading Engine)

**Fully standalone** - no dependency on Demo1 or Demo1_ML folders. Live1 contains all necessary strategy logic and can be deployed independently.

This folder contains a **live** (demo-first) version of the `Demo1` strategy.
Instead of backtesting, it connects to MT5, detects setups at the **D1 rollover**, places **pending limit orders**, and then continuously tracks orders/positions/deals with **partial profit management**.

## What it does (V1.2)

- Scans symbols for the same **2-candle exhaustion** pattern used in `Demo1`.
- On each new D1 day per symbol:
  - Builds/validates **unfilled FVGs** from C2 M5 candles
  - Selects **Option C: best R** setup (highest estimated R multiple)
  - SL: uses the existing extreme logic (validation → formation window)
  - TP: **C1 midpoint**
  - Places a **pending limit** order immediately at D1 rollover
- Risk sizing: **0.5% of balance** (default), sized by **SL distance** (tick-value based sizing).
- **Partial Profit Management** (NEW in V1.2):
  - **Conservative mode (default)**: When position opens with TP > 3R, automatically modifies TP to 3R. When price reaches 3R, closes 50% of position, moves SL to breakeven, and restores original TP on remaining 50%.
  - **Aggressive mode**: No partial profit taking - positions run full size to original TP or SL.
  - Positions with TP ≤ 3R are left unmodified and run to their original targets.
- Spread handling:
  - Reads current spread at placement time.
  - For BUY LIMIT (Bullish): adjusts entry `validation_level + spread` so the order fills when bid hits the validation level (typical bid-based candle levels).
- Trade lifecycle logging:
  - Polls pending orders and positions filtered by `magic_number`
  - Polls deal history to log fills/closures
  - Tracks partial profit executions and TP modifications
  - Stores events to JSONL and state to JSON for restart safety
- Weekend awareness:
  - Detects weekend via MT5 server tick time and pauses new order placement (keeps running/logging).

## Folder layout

- `app.py` — main live loop / runner
- `config.py` — configuration (risk %, retries, spread adjustment, magic number, symbols, **trading_mode**)
- `config.example.py` — template configuration for deployment
- `mt5_adapter.py` — MT5 connection, candle fetch, ticks/spread, order send/cancel, history access, **position modification**
- `risk.py` — position sizing from SL distance and account balance
- `execution.py` — pending limit order placement + retry policy
- `trade_manager.py` — reconciliation loop (orders/positions/deals logging + expiry cleanup)
- `partial_manager.py` — monitors positions, modifies TP to 3R, executes partials, restores original TP
- `storage.py` — `state.json` + `events.jsonl` persistence (includes partial profit tracking)
- `strategy/`
  - `fvg.py` — FVG detection + validation logic
  - `select_setup.py` — selects the best-R validated setup and computes SL/TP
  - `pattern_detection.py` — core pattern detection (exhaustion pattern, SL/TP calculation)
- `requirements.txt` — Python dependencies (MetaTrader5, pandas, matplotlib)
- `.gitignore` — excludes runtime files (state.json, events.jsonl, __pycache__)
- `DEPLOYMENT.md` — comprehensive deployment checklist and safety guidelines

## How to run

1. Open MT5 and log into your **demo** account.
2. In a terminal at the workspace root:

```powershell
cd "C:\Users\user\Desktop\Demo"
python Live1\app.py
```

Stop with `Ctrl+C`.

## GUI (optional)

If you'd rather watch Live1 in a window (instead of the terminal), run:

```powershell
cd "C:\Users\user\Desktop\Demo"
python Live1\gui_app.py
```

Then click **Start Live1**. The GUI streams `events.jsonl` live and also shows startup errors/output if any.

## Logs & state

- `Live1/state.json`
  - Tracks last seen D1 start per symbol
  - Tracks last deal-history poll time
  - Tracks last weekend notice date
  - **NEW**: Tracks positions with TP modified to 3R (`positions_at_3r_tp`)
  - **NEW**: Tracks positions that had partial profits taken (`partials_taken`)

- `Live1/events.jsonl`
  - Append-only event log (order placement attempts, order/position changes, deals, weekend mode)
  - **NEW**: Partial profit events (`tp_modified_to_3r`, `partial_close_success`, `tp_restored_sl_to_be`, `cleanup_3r_tp_positions`)

## Key configuration
- `risk_per_trade_pct` — default 0.5% (changed from 1.0%)
- `retries` / `retry_delay_seconds` — currently 5 retries, 2 seconds
- `magic_number` — used to filter/manage only this bot's orders
- `adjust_buy_limit_for_spread` — adjusts BUY LIMIT entry using current spread
- `symbols` — set a tuple like `("EURUSD.x", "GBPUSD.x")` to limit trading, or leave `None` for all detected forex symbols
- **`trading_mode`** — **NEW**: `"conservative"` (default) or `"aggressive"`
  - **Conservative**: Takes 50% profit at 3R, moves SL to breakeven, lets remaining 50% run to full TP
  - **Aggressive**: No partial profit taking, holds full position until TP or SL

## Partial Profit Strategy (Conservative Mode)

### How It Works:

1. **Position Opens** (with TP > 3R):
   - System immediately modifies TP from original to 3R
   - Stores original TP in state for later restoration
   - Example: Original TP is 5R → Modified to 3R temporarily

2. **Price Reaches 3R**:
   - Automatically closes 50% of position volume
   - Locks in 1.5R profit (50% of 3R)

3. **After Partial Taken**:
   - Moves SL to breakeven (entry price) → Risk-free trade
   - Restores TP back to original target (5R in example)
   - Remaining 50% now runs to full 5R potential

### Special Cases:

- **Positions with TP ≤ 3R**: Not modified, run to original targets
- **Failed Modifications**: Logged but don't block trade execution
- **Volume Precision**: Respects broker's minimum lot size and volume step
- **State Cleanup**: Automatically removes closed positions from tracking
- `magic_number` — used to filter/manage only this bot’s orders
- `adjust_buy_limit_for_spread` — adjusts BUY LIMIT entry using current spread
- `symbols` — set a tuple like `("EURUSD.x", "GBPUSD.x")` to limit trading, or leave `None` for all detected forex symbols

## Notes / assumptions

- The engine places orders immediately at **D1 rollover** (even if the first M5 candle hasn’t fully formed yet), because price can hit the level quickly.
- There is a safety check to skip invalid pending limits:
  - BUY LIMIT must be below current ask
  - SELL LIMIT must be above current bid
- **Partial profit management** only activates for positions with TP > 3R in conservative mode
- Position modifications (TP changes, partial closes) use proper volume rounding per broker requirements

## Version History

- **V1.2** (Current): Added conservative/aggressive trading modes with partial profit management at 3R
- **V1.1**: Initial live trading with pending orders, spread adjustment, and weekend awareness
- **V1.0**: Basic setup detection and order placement

## Next improvements (V3 ideas)

- Place multiple setups per symbol (not only best-R)
- More robust order/position linking (order → position mapping)
- Time-based exits or trailing stops
- Stronger weekend/market-closed detection per symbol
- Configurable partial profit levels (2R, 3R, 4R options)
