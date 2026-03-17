
import ccxt
import pandas as pd
import pandas_ta as ta
import numpy as np
import requests
import time
from datetime import datetime
import sys
import os

# Ավելացնում ենք scratch թղթապանակը path-ի մեջ, որպեսզի ներմուծենք bot-ի ֆունկցիաները
sys.path.append(r'C:\Users\And\.gemini\antigravity\scratch\test')
from crypto_bot import get_data, analyze_data, get_historical_winrate

def test():
    symbol = 'BTC/USDT'
    timeframe = '1h'
    print(f"--- Verification for {symbol} ({timeframe}) ---")
    
    # Get 1000 candles as in the new code
    df = get_data(symbol, timeframe, limit=1000)
    df = analyze_data(df)
    
    b_wr, b_tot, s_wr, s_tot = get_historical_winrate(df)
    
    print(f"Buy Winrate: {b_wr:.2f}% (Total Signals: {b_tot})")
    print(f"Sell Winrate: {s_wr:.2f}% (Total Signals: {s_tot})")
    
    if b_tot > 0 or s_tot > 0:
        print("OK: Win-rate calculation is working.")
    else:
        print("ERROR: No signals found, try another pair.")

if __name__ == "__main__":
    test()
