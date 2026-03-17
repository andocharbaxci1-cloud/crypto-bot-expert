
import ccxt
import pandas as pd
import pandas_ta as ta
import numpy as np
import sys

sys.path.append(r'C:\Users\And\.gemini\antigravity\scratch\test')
from crypto_bot import get_data, analyze_data

exchange = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'spot'}})
SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT']

def diagnose_scalp(symbol, timeframe):
    print(f"\n--- Diagnosing {symbol} ({timeframe}) ---")
    try:
        df = get_data(symbol, timeframe, limit=100)
        df = analyze_data(df)
        last_row = df.iloc[-2]
        prev_row = df.iloc[-3]
        
        close = last_row['close']
        atr = last_row['ATRr_14']
        lower_bb = last_row['BBL_20_2.0_2.0']
        upper_bb = last_row['BBU_20_2.0_2.0']
        rsi = last_row['RSI_14']
        macd = last_row['MACD_12_26_9']
        macd_signal = last_row['MACDs_12_26_9']
        
        volatility = (atr * 3) / close
        print(f"Volatility (atr*3/price): {volatility:.4f} (Threshold: 0.0150)")
        if volatility < 0.015:
            print("FAILED: Market is too sleepy (Low volatility)")
        
        # BUY conditions
        bb_touch_buy = (last_row['low'] <= lower_bb or prev_row['low'] <= prev_row['BBL_20_2.0_2.0'])
        rsi_buy = (rsi > prev_row['RSI_14'] and rsi < 45)
        macd_buy = (macd > macd_signal and prev_row['MACD_12_26_9'] <= prev_row['MACDs_12_26_9'])
        
        print(f"BUY Conditions: BB Touch: {bb_touch_buy}, RSI: {rsi_buy} (RSI: {rsi:.1f}, Prev: {prev_row['RSI_14']:.1f}), MACD: {macd_buy}")
        
        # SELL conditions
        bb_touch_sell = (last_row['high'] >= upper_bb or prev_row['high'] >= prev_row['BBU_20_2.0_2.0'])
        rsi_sell = (rsi < prev_row['RSI_14'] and rsi > 55)
        macd_sell = (macd < macd_signal and prev_row['MACD_12_26_9'] >= prev_row['MACDs_12_26_9'])
        
        print(f"SELL Conditions: BB Touch: {bb_touch_sell}, RSI: {rsi_sell} (RSI: {rsi:.1f}, Prev: {prev_row['RSI_14']:.1f}), MACD: {macd_sell}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    for s in SYMBOLS:
        diagnose_scalp(s, '5m')
