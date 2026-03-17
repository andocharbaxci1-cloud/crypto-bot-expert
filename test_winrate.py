
import ccxt
import pandas as pd
import pandas_ta as ta
import numpy as np
import requests
import time
from datetime import datetime

# Mock SYMBOLS and exchange for testing
SYMBOLS = ['BTC/USDT']
exchange = ccxt.binance({
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

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

def get_historical_winrate(df):
    buy_wins, buy_tot, sell_wins, sell_tot = 0, 0, 0, 0
    print("Columns in DF:", df.columns.tolist())
    for i in range(200, len(df)-10):
        if pd.isna(df['EMA_200'].iloc[i]): continue
            
        c = df['close'].iloc[i]; e50 = df['EMA_50'].iloc[i]; e200 = df['EMA_200'].iloc[i]
        rs = df['RSI_14'].iloc[i]; 
        
        # Check if columns exist
        mac_col = 'MACD_12_26_9'
        macs_col = 'MACDs_12_26_9'
        at_col = 'ATRr_14'
        l_bb_col = 'BBL_20_2.0_2.0'
        u_bb_col = 'BBU_20_2.0_2.0'
        
        if mac_col not in df.columns:
            print(f"Column {mac_col} not found!")
            continue
            
        mac = df[mac_col].iloc[i]; macs = df[macs_col].iloc[i]
        at = df[at_col].iloc[i]; l_bb = df[l_bb_col].iloc[i]; u_bb = df[u_bb_col].iloc[i]
        
        if (e50 > e200) and (rs < 40 or c <= l_bb) and (mac > macs):
            buy_tot += 1; tp = c + (at*3); sl = c - (at*1.5)
            hit = False
            for j in range(i+1, min(i+15, len(df))):
                if df['high'].iloc[j] >= tp: 
                    buy_wins+=1; hit=True; break
                elif df['low'].iloc[j] <= sl: 
                    hit=True; break
            if not hit:
                print(f"BUY Signal at {i}: Entry={c:.2f}, TP={tp:.2f}, SL={sl:.2f}, ATR={at:.2f} - No hit in 15 candles")
                pass
        elif (e50 < e200) and (rs > 60 or c >= u_bb) and (mac < macs):
            sell_tot += 1; tp = c - (at*3); sl = c + (at*1.5)
            hit = False
            for j in range(i+1, min(i+15, len(df))):
                if df['low'].iloc[j] <= tp: 
                    sell_wins+=1; hit=True; break
                elif df['high'].iloc[j] >= sl: 
                    hit=True; break
            if not hit:
                print(f"SELL Signal at {i}: Entry={c:.2f}, TP={tp:.2f}, SL={sl:.2f}, ATR={at:.2f} - No hit in 15 candles")
                pass
    b_wr = (buy_wins/(buy_tot+0.001)*100); s_wr = (sell_wins/(sell_tot+0.001)*100)
    return b_wr, buy_tot, s_wr, sell_tot

try:
    df = get_data('BTC/USDT', '1h', limit=1000)
    df = analyze_data(df)
    b_wr, buy_tot, s_wr, sell_tot = get_historical_winrate(df)
    print(f"Buy Winrate: {b_wr:.2f}% (Total: {buy_tot})")
    print(f"Sell Winrate: {s_wr:.2f}% (Total: {sell_tot})")
except Exception as e:
    print(f"Error: {e}")
