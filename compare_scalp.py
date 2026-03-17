
import ccxt
import pandas as pd
import pandas_ta as ta
import numpy as np
import sys

sys.path.append(r'C:\Users\And\.gemini\antigravity\scratch\test')
from crypto_bot import get_data, analyze_data

def test_scalp_logic(df, mode='strict'):
    buy_wins, buy_tot, sell_wins, sell_tot = 0, 0, 0, 0
    tp_pct = 0.007  # 0.7%
    sl_pct_max = 0.015 # 1.5%
    
    start_idx = max(50, int(len(df) * 0.1))
    
    for i in range(start_idx, len(df) - 20):
        last_row = df.iloc[i]
        prev_row = df.iloc[i-1]
        close = last_row['close']
        lower_bb = last_row['BBL_20_2.0_2.0']
        upper_bb = last_row['BBU_20_2.0_2.0']
        rsi = last_row['RSI_14']
        macd = last_row['MACD_12_26_9']
        macd_signal = last_row['MACDs_12_26_9']
        atr = last_row['ATRr_14']

        # Volatility check
        if (atr * 3) / close < 0.008: continue

        # BUY Logic
        bb_buy = (last_row['low'] <= lower_bb or prev_row['low'] <= prev_row['BBL_20_2.0_2.0'])
        rsi_buy = (rsi > prev_row['RSI_14'] and rsi < 45)
        macd_buy = (macd > macd_signal and prev_row['MACD_12_26_9'] <= prev_row['MACDs_12_26_9'])
        
        signal_buy = False
        if mode == 'strict':
            if bb_buy and rsi_buy and macd_buy: signal_buy = True
        else: # Flexible: MACD not mandatory
            if bb_buy and rsi_buy: signal_buy = True

        if signal_buy:
            buy_tot += 1
            entry = close
            sl = min(last_row['low'], prev_row['low']) - (atr * 0.5)
            if (entry - sl) / entry > sl_pct_max: sl = entry * (1 - sl_pct_max)
            tp = entry * (1 + tp_pct)
            for j in range(i+1, min(i+21, len(df))):
                if df['high'].iloc[j] >= tp: buy_wins += 1; break
                elif df['low'].iloc[j] <= sl: break

        # SELL Logic
        bb_sell = (last_row['high'] >= upper_bb or prev_row['high'] >= prev_row['BBU_20_2.0_2.0'])
        rsi_sell = (rsi < prev_row['RSI_14'] and rsi > 55)
        macd_sell = (macd < macd_signal and prev_row['MACD_12_26_9'] >= prev_row['MACDs_12_26_9'])
        
        signal_sell = False
        if mode == 'strict':
            if bb_sell and rsi_sell and macd_sell: signal_sell = True
        else:
            if bb_sell and rsi_sell: signal_sell = True

        if signal_sell:
            sell_tot += 1
            entry = close
            sl = max(last_row['high'], prev_row['high']) + (atr * 0.5)
            if (sl - entry) / entry > sl_pct_max: sl = entry * (1 + sl_pct_max)
            tp = entry * (1 - tp_pct)
            for j in range(i+1, min(i+21, len(df))):
                if df['low'].iloc[j] <= tp: sell_wins += 1; break
                elif df['high'].iloc[j] >= sl: break
                
    wr = ((buy_wins + sell_wins) / (buy_tot + sell_tot + 0.001)) * 100
    return wr, (buy_tot + sell_tot)

symbol = 'SOL/USDT'
print(f"Comparing Scalp strategies for {symbol} (5m) over 1000 candles:")
try:
    df = get_data(symbol, '5m', limit=1000)
    df = analyze_data(df)
    
    wr_s, tot_s = test_scalp_logic(df, 'strict')
    wr_f, tot_f = test_scalp_logic(df, 'flexible')
    
    print(f"STRICT (BB + RSI + MACD):  WR: {wr_s:.1f}%, Signals: {tot_s}")
    print(f"FLEXIBLE (BB + RSI):       WR: {wr_f:.1f}%, Signals: {tot_f}")
except Exception as e:
    print(f"Error: {e}")
