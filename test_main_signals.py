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
    return df

def test_1h_4h():
    symbol = 'DOGE/USDT' # Taking a volatile coin as example
    
    print(f"--- Diagnostic: Why no 1h/4h signals for {symbol}? ---")
    
    # 1. Fetch BTC Trend
    df_btc_4h = analyze_data(get_data('BTC/USDT', '4h', limit=250))
    df_btc_1h = analyze_data(get_data('BTC/USDT', '1h', limit=100))
    df_btc_1h.ta.ema(length=20, append=True)
    
    last_b4 = df_btc_4h.iloc[-2]
    last_b1 = df_btc_1h.iloc[-2]
    
    slow_trend = "NEUTRAL"
    if last_b4['close'] > last_b4['EMA_200'] and last_b4['EMA_50'] > last_b4['EMA_200']:
        slow_trend = "UPTREND"
    elif last_b4['close'] < last_b4['EMA_200'] and last_b4['EMA_50'] < last_b4['EMA_200']:
        slow_trend = "DOWNTREND"
        
    fast_trend = "NEUTRAL"
    if last_b1['close'] > last_b1['EMA_50'] and last_b1['EMA_20'] > last_b1['EMA_50']:
        fast_trend = "UPTREND"
    elif last_b1['close'] < last_b1['EMA_50'] and last_b1['EMA_20'] < last_b1['EMA_50']:
        fast_trend = "DOWNTREND"
        
    btc_trend = slow_trend
    if fast_trend == "UPTREND": btc_trend = "UPTREND"
    elif slow_trend == "UPTREND" and fast_trend == "DOWNTREND": btc_trend = "NEUTRAL"
    
    print(f"Global BTC Trend: {btc_trend}\n")
    
    # 2. Check 1h and 4h logic
    for tf in ['1h', '4h']:
        print(f"--- Testing {symbol} on {tf} ---")
        df = analyze_data(get_data(symbol, tf, limit=250))
        df.ta.ema(length=20, append=True)
        last = df.iloc[-2]
        
        close = last['close']
        ema20 = last['EMA_20']
        ema50 = last['EMA_50']
        ema200 = last['EMA_200']
        rsi = last['RSI_14']
        macd = last['MACD_12_26_9']
        macd_signal = last['MACDs_12_26_9']
        lower_bb = last['BBL_20_2.0_2.0']
        upper_bb = last['BBU_20_2.0_2.0']

        print(f"Price: {close:.5f}")
        print(f"EMA50: {ema50:.5f}, EMA200: {ema200:.5f}")
        print(f"RSI: {rsi:.2f}")
        print(f"MACD: {macd:.5f}, MACD Signal: {macd_signal:.5f}")
        print(f"Lower BB: {lower_bb:.5f}, Upper BB: {upper_bb:.5f}")
        
        print("\n--- Strategy Check ---")
        
        # BUY Confluence
        is_uptrend = (ema20 > ema50) and (ema50 > ema200)
        pullback_support = (last['low'] <= ema20 * 1.005) and (close >= ema50)
        
        try:
            prev_rsi = df.iloc[-3]['RSI_14']
        except:
            prev_rsi = 50
            
        momentum_up = (macd > macd_signal) and (rsi > prev_rsi)
        
        print(f"BUY (Trend Continuation) Conditions:")
        print(f" 1. UPTREND (EMA20 > EMA50 > EMA200): {is_uptrend}")
        print(f"    - EMA20: {ema20:.5f}, EMA50: {ema50:.5f}, EMA200: {ema200:.5f}")
        print(f" 2. Pullback to Support (Low <= EMA20 and Close >= EMA50): {pullback_support}")
        print(f"    - Low: {last['low']:.5f}, EMA20: {ema20:.5f}, Close: {close:.5f}, EMA50: {ema50:.5f}")
        print(f" 3. Momentum Up (MACD > Signal AND RSI Bouncing): {momentum_up}")
        print(f"    - RSI: {rsi:.2f}, Prev RSI: {prev_rsi:.2f}")
        print(f" 4. BTC Filter (Not DOWNTREND): {btc_trend != 'DOWNTREND'}")
        
        if is_uptrend and pullback_support and momentum_up and btc_trend != 'DOWNTREND':
            print(">>> BUY SIGNAL TRIGGERED! <<<")
        else:
            print(">>> MISSING BUY CONDITIONS. <<<")
            
        print("\n---")
        # SELL Confluence
        is_downtrend = (ema20 < ema50) and (ema50 < ema200)
        pullback_resist = (last['high'] >= ema20 * 0.995) and (close <= ema50)
        momentum_down = (macd < macd_signal) and (rsi < prev_rsi)
        
        print(f"SELL (Trend Continuation) Conditions:")
        print(f" 1. DOWNTREND (EMA20 < EMA50 < EMA200): {is_downtrend}")
        print(f" 2. Pullback to Resist (High >= EMA20 and Close <= EMA50): {pullback_resist}")
        print(f" 3. Momentum Down (MACD < Signal AND RSI Dropping): {momentum_down}")
        print(f" 4. BTC Filter (Not UPTREND): {btc_trend != 'UPTREND'}")
        
        if is_downtrend and pullback_resist and momentum_down and btc_trend != 'UPTREND':
            print(">>> SELL SIGNAL TRIGGERED! <<<")
        else:
            print(">>> MISSING SELL CONDITIONS. <<<")
        print("===============================\n")

if __name__ == "__main__":
    test_1h_4h()
