"""
Test script to verify automatic forex symbol detection.
Run this to see what symbols would be auto-detected on your broker.
"""

from __future__ import annotations
import sys
from pathlib import Path

# Ensure Live1 package is importable
try:
    import Live1.mt5_adapter as mt5a
except ModuleNotFoundError:
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    import Live1.mt5_adapter as mt5a


def main():
    print("=" * 70)
    print("Testing Automatic Forex Symbol Detection")
    print("=" * 70)
    
    # Initialize MT5
    if not mt5a.initialize():
        print("\n❌ Failed to initialize MT5. Make sure MT5 is running and logged in.")
        return
    
    try:
        print("\n1. Testing auto_detect_forex_symbols()...")
        print("-" * 70)
        
        auto_symbols = mt5a.auto_detect_forex_symbols()
        
        if auto_symbols:
            print(f"\n✅ Auto-detected {len(auto_symbols)} forex symbols:")
            for i, symbol in enumerate(auto_symbols, 1):
                print(f"   {i:2d}. {symbol}")
        else:
            print("\n⚠️  No symbols auto-detected")
        
        print("\n2. Testing legacy get_forex_symbols() for comparison...")
        print("-" * 70)
        
        legacy_symbols = mt5a.get_forex_symbols()
        
        if legacy_symbols:
            print(f"\n✅ Legacy method found {len(legacy_symbols)} forex symbols:")
            for i, symbol in enumerate(legacy_symbols[:20], 1):  # Show first 20
                print(f"   {i:2d}. {symbol}")
            if len(legacy_symbols) > 20:
                print(f"   ... and {len(legacy_symbols) - 20} more")
        else:
            print("\n⚠️  Legacy method found no symbols")
        
        print("\n3. Comparison:")
        print("-" * 70)
        if auto_symbols and legacy_symbols:
            auto_set = set(auto_symbols)
            legacy_set = set(legacy_symbols)
            
            in_auto_only = auto_set - legacy_set
            in_legacy_only = legacy_set - auto_set
            in_both = auto_set & legacy_set
            
            print(f"   • In both methods: {len(in_both)}")
            print(f"   • Auto-detect only: {len(in_auto_only)}")
            if in_auto_only:
                print(f"     {', '.join(list(in_auto_only)[:10])}")
            print(f"   • Legacy only: {len(in_legacy_only)}")
            if in_legacy_only:
                print(f"     {', '.join(list(in_legacy_only)[:10])}")
        
        print("\n" + "=" * 70)
        print("✅ Test completed successfully!")
        print("=" * 70)
        
    finally:
        mt5a.shutdown()


if __name__ == "__main__":
    main()
