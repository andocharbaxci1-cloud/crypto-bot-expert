
import ccxt
import pandas as pd
import pandas_ta as ta
import numpy as np
import sys

sys.path.append(r'C:\Users\And\.gemini\antigravity\scratch\test')
from crypto_bot import get_data, analyze_data, get_historical_winrate

SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
TIMEFRAMES = {
    '5m': 'scalp',
    '15m': 'scalp',
    '1h': 'indicator',
    '4h': 'indicator'
}

print("Analysing expected accuracy (Win-Rate) based on historical data (1000 candles)...")
for symbol in SYMBOLS:
    print(f"\n--- {symbol} ---")
    for tf, mode in TIMEFRAMES.items():
        try:
            df = get_data(symbol, tf, limit=1000)
            df = analyze_data(df)
            
            b_wr, b_t, s_wr, s_t = get_historical_winrate(df, mode=mode)
            
            avg_wr = (b_wr * b_t + s_wr * s_t) / (b_t + s_t + 0.001)
            total = b_t + s_t
            print(f"{tf}: {avg_wr:.1f}% WR (Signals: {total})")
        except Exception as e:
            print(f"{tf}: Error {e}")
