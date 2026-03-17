import ccxt
import pandas as pd
import pandas_ta as ta
from datetime import datetime

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
    df.ta.ema(length=20, append=True)
    return df

def test_relaxed_logic():
    symbol = 'SOL/USDT'
    print(f"--- Testing Relaxed Logic for {symbol} ---")
    
    df = analyze_data(get_data(symbol, '1h', limit=500))
    last = df.iloc[-2]
    prev = df.iloc[-3]
    
    close = last['close']
    e20 = last['EMA_20']
    e50 = last['EMA_50']
    mac = last['MACD_12_26_9']
    macs = last['MACDs_12_26_9']
    rsi = last['RSI_14']
    prsi = prev['RSI_14']
    
    print(f"Price: {close}, EMA20: {e20}, EMA50: {e50}")
    print(f"MACD: {mac}, MACD_S: {macs}, RSI: {rsi}, Prev_RSI: {prsi}")
    
    # New Relaxed BUY
    cond_buy = (e20 > e50) and (last['low'] <= e20*1.005) and (mac > macs) and (rsi > prsi)
    print(f"Relaxed BUY Condition (e20>e50 and pullback and momentum): {cond_buy}")
    
    # New Relaxed SELL
    cond_sell = (e20 < e50) and (last['high'] >= e20*0.995) and (mac < macs) and (rsi < prsi)
    print(f"Relaxed SELL Condition (e20<e50 and pullback and momentum): {cond_sell}")

if __name__ == "__main__":
    test_relaxed_logic()
