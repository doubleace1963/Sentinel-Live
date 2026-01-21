# Automatic Forex Symbol Detection Feature

## Overview
The Live1 trading application now automatically detects and adds forex symbols when connecting to a broker account if no symbols are configured in `config.py`.

## How It Works

### 1. Symbol Detection Logic
When `CONFIG.symbols` is `None` or empty, the application will:

1. **Auto-detect standard forex pairs** using the new `auto_detect_forex_symbols()` function
2. Automatically handle broker-specific suffixes (e.g., `.x`, `z`, `.raw`, `.pro`)
3. Verify each symbol is selectable/visible in MT5
4. Log the detected symbols to the events log

### 2. Supported Forex Pairs

The auto-detection covers 28 standard forex pairs:

**Major Pairs:**
- EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, USDCAD, NZDUSD

**EUR Crosses:**
- EURGBP, EURJPY, EURCHF, EURAUD, EURCAD, EURNZD

**GBP Crosses:**
- GBPJPY, GBPCHF, GBPAUD, GBPCAD, GBPNZD

**AUD Crosses:**
- AUDJPY, AUDCHF, AUDCAD, AUDNZD

**Other Crosses:**
- CADJPY, CHFJPY, NZDJPY

### 3. Broker Suffix Support

The system recognizes common broker naming conventions:

| Broker Type | Example | Detection |
|------------|---------|-----------|
| Standard | EURUSD | Exact match |
| GoatFunded | EURUSD.x | Detects `.x` suffix |
| Enxess | EURUSDz | Detects single letter suffix |
| ECN/Raw | EURUSD.raw | Detects `.raw`, `.ecn`, `.std` |
| Pro accounts | EURUSD.pro | Detects `.pro`, `.m` |

### 4. Fallback Mechanism

If auto-detection finds no symbols, it falls back to the legacy `get_forex_symbols()` method which uses broker path detection (looks for "FX" in symbol path).

## Configuration

### Enable Auto-Detection
In your `config.py`, set `symbols` to `None`:

```python
CONFIG = LiveConfig(
    symbols=None,  # Enable auto-detection
    # ... other config
)
```

### Manual Symbol Configuration
To manually specify symbols (disables auto-detection):

```python
CONFIG = LiveConfig(
    symbols=("EURUSD.x", "GBPUSD.x", "USDJPY.x"),  # Manual list
    # ... other config
)
```

## Usage

### Starting the Application

When starting Live1 with no configured symbols, you'll see:

```
No symbols configured in config.symbols, attempting auto-detection...
Auto-detected 28 forex symbols: EURUSD.x, GBPUSD.x, USDJPY.x, USDCHF.x, AUDUSD.x, USDCAD.x, NZDUSD.x, EURGBP.x, EURJPY.x, EURCHF.x...
Live1 running on 28 symbols
```

### GUI Display

The GUI will show the symbol source in the MT5 status line:
- `MT5: connected (symbols: auto-detect)` - Using auto-detection
- `MT5: connected (symbols: configured)` - Using manual configuration

### Event Logging

When symbols are auto-detected, an event is logged:

```json
{
  "time": "2026-01-21T10:30:00",
  "type": "auto_detected_symbols",
  "payload": {
    "count": 28,
    "symbols": ["EURUSD.x", "GBPUSD.x", ...]
  }
}
```

## Testing

Run the test script to see what symbols would be detected on your broker:

```powershell
python Live1\test_symbol_detection.py
```

This will show:
- Symbols detected by auto-detection
- Symbols detected by legacy method
- Comparison between the two methods

## Files Modified

1. **mt5_adapter.py**: Added `auto_detect_forex_symbols()` function
2. **app.py**: Updated startup logic to use auto-detection when symbols not configured
3. **gui_app.py**: Added symbol source display in MT5 status

## Benefits

✅ **No manual configuration needed** - Works out of the box with any broker
✅ **Broker-agnostic** - Handles different symbol naming conventions automatically
✅ **Smart detection** - Focuses on standard forex pairs, avoiding exotic symbols
✅ **Verified symbols** - Only uses symbols that are selectable/visible in MT5
✅ **Transparent** - Logs which symbols were detected for troubleshooting

## Troubleshooting

### No symbols detected
- Ensure MT5 is connected to the broker and logged in
- Check if forex symbols are available in MT5 Market Watch
- Try manually adding one forex symbol to Market Watch, then restart the app

### Wrong symbols detected
- Use manual configuration instead: set `symbols=("EURUSD", "GBPUSD", ...)` in config.py
- Check the test script output to see what's being detected

### Broker uses unusual suffix
If your broker uses a unique suffix pattern not recognized, either:
1. Manually configure symbols in config.py
2. Contact support to add the suffix pattern to the auto-detection logic
