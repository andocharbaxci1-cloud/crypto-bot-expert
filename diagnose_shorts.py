import ccxt
import pandas as pd
import pandas_ta as ta
import time
from datetime import datetime

# Import bot logic (we'll just copy the relevant parts to be safe and independent)
exchange = ccxt.binance({'options': {'defaultType': 'future'}})

def get_data(symbol, timeframe, limit=300):
    bars = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

def analyze_data(df):
    df.ta.macd(append=True)                 
    df.ta.rsi(length=14, append=True)       
    df.ta.ema(length=50, append=True)       
    df.ta.ema(length=200, append=True)      
    df.ta.bbands(length=20, append=True)    
    df.ta.atr(length=14, append=True)       
    # Add EMA20 for 1h trend checks
    df.ta.ema(length=20, append=True)
    return df

def diagnostic():
    print(f"--- Diagnostic Run: {datetime.now()} ---")
    
    # 1. Check BTC Trend
    try:
        df_4h = get_data('BTC/USDT', '4h', limit=250)
        df_4h = analyze_data(df_4h)
        last_4h = df_4h.iloc[-2]
        
        df_1h = get_data('BTC/USDT', '1h', limit=100)
        df_1h = analyze_data(df_1h)
        last_1h = df_1h.iloc[-2]
        
        slow_trend = "NEUTRAL"
        if last_4h['close'] > last_4h['EMA_200'] and last_4h['EMA_50'] > last_4h['EMA_200']:
            slow_trend = "UPTREND"
        elif last_4h['close'] < last_4h['EMA_200'] and last_4h['EMA_50'] < last_4h['EMA_200']:
            slow_trend = "DOWNTREND"
            
        fast_trend = "NEUTRAL"
        if last_1h['close'] > last_1h['EMA_50'] and last_1h['EMA_20'] > last_1h['EMA_50']:
            fast_trend = "UPTREND"
        elif last_1h['close'] < last_1h['EMA_50'] and last_1h['EMA_20'] < last_1h['EMA_50']:
            fast_trend = "DOWNTREND"
            
        print(f"BTC 4h Trend: {slow_trend} (EMA50: {last_4h['EMA_50']:.0f}, EMA200: {last_4h['EMA_200']:.0f}, Close: {last_4h['close']:.0f})")
        print(f"BTC 1h Trend: {fast_trend} (EMA20: {last_1h['EMA_20']:.0f}, EMA50: {last_1h['EMA_50']:.0f}, Close: {last_1h['close']:.0f})")
        
        final_trend = slow_trend
        if slow_trend == "DOWNTREND" and fast_trend == "UPTREND":
            final_trend = "NEUTRAL"
        print(f"Final Global Trend Decision: {final_trend}")
        
    except Exception as e:
        print(f"Error checking BTC: {e}")

    # 2. Check DOGE/USDT (Commonly mentioned by user)
    try:
        symbol = 'DOGE/USDT'
        tf = '1h'
        df = get_data(symbol, tf, limit=100)
        df = analyze_data(df)
        last = df.iloc[-2]
        
        print(f"\n--- {symbol} ({tf}) Indicators ---")
        print(f"Price: {last['close']:.5f}")
        print(f"EMA50: {last['EMA_50']:.5f}, EMA200: {last['EMA_200']:.5f}")
        print(f"RSI: {last['RSI_14']:.2f}")
        print(f"Upper BB: {last['BBU_20_2.0_2.0']:.5f}")
        
        # Check logic for check_signals SHORT
        cond1 = (last['EMA_50'] < last['EMA_200'])
        cond2 = (last['RSI_14'] > 60 or last['close'] >= last['BBU_20_2.0_2.0'])
        cond3 = (last['MACD_12_26_9'] < last['MACDs_12_26_9'])
        
        print(f"SHORT Conditions for check_signals:")
        print(f" - EMA50 < EMA200 (Long-term Bearish): {cond1}")
        print(f" - RSI>60 or Price >= UpperBB (Overbought): {cond2}")
        print(f" - MACD < Signal (Bearish Cross): {cond3}")
        
        trigger = cond1 and cond2 and cond3
        print(f"Would trigger SHORT in NEUTRAL? {trigger}")
        
    except Exception as e:
        print(f"Error checking DOGE: {e}")

if __name__ == "__main__":
    diagnostic()
