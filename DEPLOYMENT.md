# Live1 Deployment Checklist

## ✅ Standalone Operation

**Live1 is fully independent** - no dependency on Demo1 or Demo1_ML folders.
- All strategy logic is self-contained within the Live1 folder
- Can be deployed, moved, or distributed without Demo1 files
- Pattern detection logic included in `Live1/strategy/pattern_detection.py`

## Before Going Live

### 1. Configuration
- [ ] **Change magic_number** in `config.py` to a unique value
- [ ] Review `risk_per_trade_pct` - default is 0.5%
- [ ] Set `symbols` if you want to limit trading to specific pairs
- [ ] Choose `trading_mode`: "conservative" (default) or "aggressive"
- [ ] Verify `order_comment` for MT5 identification

### 2. Testing
- [ ] Test on **DEMO account first** - at least 1 week
- [ ] Verify order placement works correctly
- [ ] Confirm partial profit logic executes at 3R (conservative mode)
- [ ] Check all event logs in `events.jsonl` for errors
- [ ] Verify restart recovery works (stop/start bot mid-trade)

### 3. Safety Checks
- [ ] Ensure `.gitignore` excludes `state.json` and `events.jsonl`
- [ ] Never commit actual account credentials or live state files
- [ ] Set appropriate `risk_per_trade_pct` (0.5-2% recommended)
- [ ] Verify duplicate protection works (try restarting during active trades)

### 4. Monitoring
- [ ] Monitor `events.jsonl` for errors and warnings
- [ ] Check MT5 terminal for order/position confirmations
- [ ] Use `gui_app.py` for real-time monitoring
- [ ] Set up alerts for critical errors (optional)

### 5. Production Readiness
- [ ] **DEMO ACCOUNT ONLY** for initial deployment
- [ ] Document your magic_number somewhere safe
- [ ] Keep backups of `state.json` (contains position tracking)
- [ ] Plan for regular log rotation of `events.jsonl`

## Going from Demo to Live

⚠️ **CRITICAL**: Only proceed after successful demo trading!

1. Close all demo positions
2. Stop the bot completely
3. Delete or archive `state.json` and `events.jsonl`
4. Change MT5 to **live account**
5. Verify config settings one more time
6. **Start with LOW risk** (0.25-0.5%)
7. Monitor closely for first few trades

## Emergency Stop

To stop the bot immediately:
- Press `Ctrl+C` in terminal (if running app.py)
- Click "Stop Live1" in GUI
- Close all positions manually in MT5 if needed

## Rollback

If issues arise:
1. Stop the bot
2. Close all open positions in MT5
3. Cancel all pending orders with the magic_number
4. Review `events.jsonl` for errors
5. Fix issues and test on demo again

## Support

- Review README.md for full documentation
- Check events.jsonl for detailed error logs
- Verify MT5 journal for broker-side issues
