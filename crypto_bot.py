import ccxt
import pandas as pd
import pandas_ta as ta
import numpy as np
import requests
import time
import os
import threading
import json
from flask import Flask
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# ================= ԿԱՐԳԱՎՈՐՈՒՄՆԵՐ =================
TELEGRAM_BOT_TOKEN = "8766650445:AAHC_xWUlHfD4qJHg3xwpGu1h60zyX_5d6w"
TELEGRAM_CHAT_IDS = ["1459989629", "6600003987"]

SYMBOLS = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT',
    'ADA/USDT', 'AVAX/USDT', 'DOGE/USDT', 'LINK/USDT', 'DOT/USDT',
    'POL/USDT', 'LTC/USDT', 'BCH/USDT', 'ATOM/USDT', 'UNI/USDT'
]
TIMEFRAMES = ['1h', '4h'] 
SCALPING_TIMEFRAMES = ['15m']

exchange = ccxt.binance({
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future'
    }
})

def get_funding_rate(symbol):
    try:
        funding = exchange.fetch_funding_rate(symbol)
        return funding.get('fundingRate', 0)
    except Exception:
        return 0

def check_manipulation(df):
    try:
        last_candle = df.iloc[-2]
        body_size = abs(last_candle['close'] - last_candle['open'])
        upper_wick = last_candle['high'] - max(last_candle['open'], last_candle['close'])
        lower_wick = min(last_candle['open'], last_candle['close']) - last_candle['low']
        if (upper_wick > body_size * 3) or (lower_wick > body_size * 3):
            return True, "⚠️ Manipulation Alert"
        return False, ""
    except Exception:
        return False, ""

SIGNAL_HISTORY = {} # Ֆորմատ՝ {(symbol, timeframe, side): timestamp}
STATS_FILE = "bot_stats.json"
TRADES_FILE = "active_trades.json"

def load_json(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except Exception:
            return default
    return default

def save_json(filepath, data):
    try:
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Սխալ {filepath} պահպանելիս:", e)

def load_stats():
    return load_json(STATS_FILE, {"date": datetime.now().strftime('%Y-%m-%d'), "signals": []})

def save_stats(stats):
    save_json(STATS_FILE, stats)

def load_active_trades():
    return load_json(TRADES_FILE, [])

def save_active_trades(trades):
    save_json(TRADES_FILE, trades)

def add_active_trade(symbol, entry, tp1, tp2, sl, side):
    trades = load_active_trades()
    trades.append({
        "symbol": symbol,
        "entry": entry,
        "tp1": tp1,
        "tp2": tp2,
        "sl": sl,
        "current_sl": sl,
        "side": side,
        "status": "ENTRY",
        "last_price": entry,
        "time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })
    save_active_trades(trades)

def record_signal(symbol, timeframe, side):
    stats = load_stats()
    today = datetime.now().strftime('%Y-%m-%d')
    if stats.get("date") != today:
        stats = {"date": today, "signals": []}
    stats["signals"].append({
        "time": datetime.now().strftime('%H:%M:%S'),
        "symbol": symbol,
        "timeframe": timeframe,
        "side": side
    })
    save_stats(stats)

def update_signal_history(symbol, timeframe, side):
    SIGNAL_HISTORY[(symbol, timeframe, side)] = time.time()

def generate_daily_report():
    stats = load_stats()
    signals = stats.get("signals", [])
    
    if not signals:
        return "📊 *Օրական Ամփոփագիր*\n\nԱյսօր ոչ մի ազդանշան չի ուղարկվել:"
    
    total = len(signals)
    today = stats.get("date")
    
    # Հաշվում ենք ամենաակտիվ մետաղը
    symbol_counts = {}
    for s in signals:
        sym = s['symbol']
        symbol_counts[sym] = symbol_counts.get(sym, 0) + 1
    
    top_symbol = max(symbol_counts, key=symbol_counts.get)
    
    msg = f"📊 *Օրական Ամփոփագիր ({today})*\n\n"
    msg += f"✅ Ընդհանուր սիգնալներ. `{total}`\n"
    msg += f"🥇 Ամենաակտիվ մետաղ. `{top_symbol}` ({symbol_counts[top_symbol]} անգամ)\n\n"
    
    msg += "📈 *Ըստ Timeframe-ների:*\n"
    tf_counts = {}
    for s in signals:
        tf = s['timeframe']
        tf_counts[tf] = tf_counts.get(tf, 0) + 1
    
    for tf, count in tf_counts.items():
        msg += f"• {tf}. `{count}` սիգնալ\n"
        
    msg += "\n💸 Շարունակիր հետևել շուկային!"
    return msg

def send_daily_report():
    msg = generate_daily_report()
    broadcast(msg)

def is_volume_significant(df, threshold=1.5, period=20):
    try:
        # Հաշվում ենք նախորդ 20 մոմերի միջին ծավալը
        avg_vol = df['volume'].iloc[-period-1:-1].mean()
        current_vol = df['volume'].iloc[-2] # Վերջին փակված մոմը
        return current_vol >= (avg_vol * threshold) if avg_vol > 0 else True
    except Exception:
        return True # Սխալի դեպքում թողնում ենք, որ սիգնալը անցնի

def get_high_volume_node(df, lookback_candles=100, bins=20):
    """
    Հաշվում է Volume Profile-ը նշված ժամանակահատվածի համար
    և վերադարձնում է այն գնային մակարդակը (High Volume Node),
    որտեղ ամենաշատ առքուվաճառքն է կատարվել:
    """
    try:
        recent_df = df.iloc[-lookback_candles-2:-2].copy()
        if recent_df.empty: return 0
        
        # Ստեղծում ենք գնային միջակայքեր (bins)
        min_p = recent_df['low'].min()
        max_p = recent_df['high'].max()
        
        if min_p == max_p: return min_p
        
        bin_size = (max_p - min_p) / bins
        volume_profile = {}
        
        for i in range(bins):
            volume_profile[min_p + (i * bin_size)] = 0
            
        # Բաշխում ենք ծավալը ըստ գնային մակարդակների
        for _, row in recent_df.iterrows():
            avg_price = (row['high'] + row['low'] + row['close']) / 3
            # Գտնում ենք համապատասխան բինը
            closest_bin = min(volume_profile.keys(), key=lambda k: abs(k - avg_price))
            volume_profile[closest_bin] += row['volume']
            
        # Գտնում ենք ամենամեծ ծավալով մակարդակը
        high_volume_node = max(volume_profile, key=volume_profile.get)
        return high_volume_node
    except Exception:
        return 0

def send_message(chat_id, text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}, timeout=10)
    except Exception as e:
        print("Սխալ նամակ ուղարկելիս:", e)

def broadcast(text):
    for cid in TELEGRAM_CHAT_IDS:
        if cid and cid != "":
            send_message(cid, text)

# == KEEP ALIVE SERVER ==
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive and running!"

def run_keep_alive():
    # Render or other services provide a PORT env var
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# == ADVANCED FEATURE 1: FEAR & GREED INDEX (ԷՄՈՑԻՈՆԱԼ ԱՆԱԼԻԶ) ==
def get_fear_and_greed_index():
    try:
        resp = requests.get('https://api.alternative.me/fng/?limit=1', timeout=10)
        if resp.status_code == 200:
            data = resp.json()['data'][0]
            val = int(data['value'])
            classification = data['value_classification']
            
            if val <= 25:
                status = "🔴 Ծայրահեղ Վախ (Extreme Fear) - *Պատմականորեն ԳՆԵԼՈՒ զոնա է*"
            elif val <= 45:
                status = "🟠 Վախ (Fear) - *Շուկան զգուշավոր է*"
            elif val <= 55:
                status = "🟡 Չեզոք (Neutral) - *Հավասարակշռված վիճակ*"
            elif val <= 75:
                status = "🟢 Ագահություն (Greed) - *Գները աճում են, բոլորը գնում են*"
            else:
                status = "🔥 Ծայրահեղ Ագահություն (Extreme Greed) - *Պատմականորեն ՎԱՃԱՌԵԼՈՒ զոնա է*"
                
            return val, status
    except Exception:
        pass
    return None, "Անհայտ"

# == ADVANCED FEATURE 4: ORDER BOOK HEATMAP (ԽՈՇՈՐ ԽԱՂԱՑՈՂՆԵՐ / ԿԵՏԵՐ) ==
def check_order_book_walls(symbol, current_price):
    try:
        # Քաշում ենք շուկայի պատվերների տետրը (Limit Orders)
        order_book = exchange.fetch_order_book(symbol, limit=50) # Նայում ենք մոտակա 50 գնային շարքերը
        
        bids = order_book['bids'] # Գնորդների պատերը (Support walls)
        asks = order_book['asks'] # Վաճառողների պատերը (Resistance walls)
        
        # Փնտրում ենք մաքսիմալ պատը (ամենամեծ Volume-ը դրված մի գնի վրա)
        max_bid = max(bids, key=lambda x: x[1]) if bids else [0, 0]
        max_ask = max(asks, key=lambda x: x[1]) if asks else [0, 0]
        
        wall_msg = ""
        # Եթե գնորդների պատերում կա որևէ աննորմալ մեծ պատվեր (օրինակ քան մյուսները 5 անգամ շատ)
        sum_bids_vol = sum(vol for price, vol in bids)
        sum_asks_vol = sum(vol for price, vol in asks)
        
        # Եթե մեկ գնի վրա խաղացողը դրել է ամբողջ գնորդների 20%-ից ավել ծավալ
        if max_bid[1] > (sum_bids_vol * 0.20): 
            perc_away = ((current_price - max_bid[0]) / current_price) * 100
            wall_msg += f"🐋 *Գնորդ Կետ (Աջակցության պատ):*\n`{max_bid[0]}` գնի վրա սպասում է հսկայական BUY օրդեր! (Հիմիկվա գնից -{perc_away:.2f}% ներքև)\n"
            
        if max_ask[1] > (sum_asks_vol * 0.20):
            perc_away = ((max_ask[0] - current_price) / current_price) * 100
            wall_msg += f"🐋 *Վաճառող Կետ (Դիմադրության պատ):*\n`{max_ask[0]}` գնի վրա կա հսկայական SELL օրդեր! Եթե գինը հասնի դրան՝ կընկնի: (+{perc_away:.2f}% վերև)\n"
            
        return wall_msg if wall_msg else "Order Book-ը մաքուր է խոշոր էքստրեմալ պատերից:\n"
    except Exception as e:
        return ""

def monitor_active_trades():
    while True:
        try:
            trades = load_active_trades()
            if not trades:
                time.sleep(60)
                continue

            updated_trades = []
            for t in trades:
                symbol = t['symbol']
                entry = t['entry']
                tp1 = t['tp1']
                tp2 = t['tp2']
                sl = t['sl']
                side = t['side']
                status = t['status']
                curr_sl = t['current_sl']

                ticker = exchange.fetch_ticker(symbol)
                price = ticker['last']
                
                remove = False
                msg = ""

                if side == 'BUY':
                    if status == "ENTRY" and price >= tp1:
                        t['status'] = "TP1_HIT"
                        t['current_sl'] = entry + (entry * 0.0005)
                        msg = f"✅ *{symbol} հասավ TP1-ին ({tp1:.4f})!*\n\n🔒 **Հրահանգ:** Տեղափոխիր Stop Loss-ը *Entry* գնի վրա` `{t['current_sl']:.4f}`:"
                    
                    elif status == "TP1_HIT" and price > t.get('last_high', entry) * 1.01:
                        t['last_high'] = price
                        new_sl = price * 0.99
                        if new_sl > curr_sl:
                            t['current_sl'] = new_sl
                            msg = f"🔥 *{symbol} շարունակում է աճել!* (Գին՝ {price:.4f})\n\n🔒 **Նոր Trailing SL:** `{new_sl:.4f}`:"

                    if price >= tp2:
                        msg = f"💰 *{symbol} հասավ TP2-ին ({tp2:.4f})!*\n\nԳործարքը ՓԱԿՎԵՑ շահույթով:"
                        remove = True
                    elif price <= curr_sl:
                        msg = f"🛑 *{symbol} փակվեց Stop Loss-ով ({curr_sl:.4f})*:"
                        remove = True

                else: 
                    if status == "ENTRY" and price <= tp1:
                        t['status'] = "TP1_HIT"
                        t['current_sl'] = entry - (entry * 0.0005)
                        msg = f"✅ *{symbol} հասավ TP1-ին ({tp1:.4f})!*\n\n🔒 **Հրահանգ:** Տեղափոխիր Stop Loss-ը *Entry* գնի վրա` `{t['current_sl']:.4f}`:"
                    
                    elif status == "TP1_HIT" and price < t.get('last_low', entry) * 0.99:
                        t['last_low'] = price
                        new_sl = price * 1.01
                        if new_sl < curr_sl:
                            t['current_sl'] = new_sl
                            msg = f"🔥 *{symbol} շարունակում է ընկնել!* (Գին՝ {price:.4f})\n\n🔒 **Նոր Trailing SL:** `{new_sl:.4f}`:"

                    if price <= tp2:
                        msg = f"💰 *{symbol} հասավ TP2-ին ({tp2:.4f})!*\n\nԳործարքը ՓԱԿՎԵՑ շահույթով:"
                        remove = True
                    elif price >= curr_sl:
                        msg = f"🛑 *{symbol} փակվեց Stop Loss-ով ({curr_sl:.4f})*:"
                        remove = True

                if msg:
                    broadcast(msg)
                
                if not remove:
                    updated_trades.append(t)
            
            save_active_trades(updated_trades)
            time.sleep(120)
        except Exception:
            time.sleep(30)

# == ԱՆԱԼԻԶ ԵՎ ԻՆԴԻԿԱՏՈՐՆԵՐ ==
def get_data(symbol, timeframe, limit=300):
    bars = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

# == BTC TREND FILTER HELPER ==
def get_btc_global_trend():
    try:
        # 1. Դանդաղ (4h) Տրենդ (EMA 50/200)
        df_4h = get_data('BTC/USDT', '4h', limit=250)
        df_4h.ta.ema(length=50, append=True)       
        df_4h.ta.ema(length=200, append=True)
        last_4h = df_4h.iloc[-2]
        
        slow_trend = "NEUTRAL"
        if last_4h['close'] > last_4h['EMA_200'] and last_4h['EMA_50'] > last_4h['EMA_200']:
            slow_trend = "UPTREND"
        elif last_4h['close'] < last_4h['EMA_200'] and last_4h['EMA_50'] < last_4h['EMA_200']:
            slow_trend = "DOWNTREND"

        # 2. Արագ (1h) Տրենդ (EMA 20/50) - Ավելի ռեակտիվ լինելու համար
        df_1h = get_data('BTC/USDT', '1h', limit=100)
        df_1h.ta.ema(length=20, append=True)
        df_1h.ta.ema(length=50, append=True)
        last_1h = df_1h.iloc[-2]

        fast_trend = "NEUTRAL"
        if last_1h['close'] > last_1h['EMA_50'] and last_1h['EMA_20'] > last_1h['EMA_50']:
            fast_trend = "UPTREND"
        elif last_1h['close'] < last_1h['EMA_50'] and last_1h['EMA_20'] < last_1h['EMA_50']:
            fast_trend = "DOWNTREND"

        # Override Logic: Եթե 1h-ը արդեն ուժեղ UPTREND է, մենք այն անվերապահորեն ընդունում ենք որպես UPTREND՝
        # որպեսզի կանխենք բոլոր SHORT սիգնալները արագ աճի (Pump) ժամանակ:
        if fast_trend == "UPTREND":
            return "UPTREND"
        elif slow_trend == "UPTREND" and fast_trend == "DOWNTREND":
            return "NEUTRAL"
            
        return slow_trend
    except Exception:
        return "NEUTRAL"

def analyze_data(df):
    df.ta.macd(append=True)                 
    df.ta.rsi(length=14, append=True)       
    df.ta.ema(length=50, append=True)       
    df.ta.ema(length=200, append=True)      
    df.ta.bbands(length=20, append=True)    
    df.ta.atr(length=14, append=True)       
    return df

def get_historical_winrate(df, mode='indicator'):
    buy_wins, buy_tot, sell_wins, sell_tot = 0, 0, 0, 0
    start_idx = max(50, int(len(df) * 0.1))
    
    for i in range(start_idx, len(df) - 50):
        if 'EMA_200' not in df.columns or pd.isna(df['EMA_200'].iloc[i]): continue
            
        c = df['close'].iloc[i]; e20 = df.get('EMA_20', df['EMA_50']).iloc[i]; e50 = df['EMA_50'].iloc[i]; e200 = df['EMA_200'].iloc[i]
        rs = df['RSI_14'].iloc[i]; mac = df['MACD_12_26_9'].iloc[i]; mac_s = df['MACDs_12_26_9'].iloc[i]
        at = df['ATRr_14'].iloc[i]; l_bb = df['BBL_20_2.0_2.0'].iloc[i]; u_bb = df['BBU_20_2.0_2.0'].iloc[i]
        low_i = df['low'].iloc[i]; high_i = df['high'].iloc[i]
        prev_rs = df['RSI_14'].iloc[i-1]; prev_mac = df['MACD_12_26_9'].iloc[i-1]; prev_mac_s = df['MACDs_12_26_9'].iloc[i-1]
        prev_l_bb = df['BBL_20_2.0_2.0'].iloc[i-1]; prev_u_bb = df['BBU_20_2.0_2.0'].iloc[i-1]
        prev_low = df['low'].iloc[i-1]; prev_high = df['high'].iloc[i-1]

        signal_buy = False
        signal_sell = False

        if mode == 'indicator':
            # NEW TREND PULLBACK LOGIC
            is_uptrend = (e20 > e50) and (e50 > e200)
            pullback_supp = (low_i <= e20 * 1.005) and (c >= e50)
            mom_up = (mac > mac_s) and (rs > prev_rs)
            if is_uptrend and pullback_supp and mom_up:
                signal_buy = True
                tp = c + (at*3.0); sl = c - (at*1.5)
                
            is_downtrend = (e20 < e50) and (e50 < e200)
            pullback_res = (high_i >= e20 * 0.995) and (c <= e50)
            mom_down = (mac < mac_s) and (rs < prev_rs)
            if is_downtrend and pullback_res and mom_down:
                signal_sell = True
                tp = c - (at*3.0); sl = c + (at*1.5)
                
        elif mode == 'scalp':
            # Scalp logic: NO MACD, Bollinger + RSI only
            if (low_i <= l_bb or prev_low <= prev_l_bb) and (rs > prev_rs and rs < 45):
                signal_buy = True
                tp = c * 1.008; sl = c * 0.992 # 0.8% TP/SL (1:1)
            elif (high_i >= u_bb or prev_high >= prev_u_bb) and (rs < prev_rs and rs > 55):
                signal_sell = True
                tp = c * 0.992; sl = c * 1.008 # 0.8% TP/SL (1:1)

        if signal_buy:
            buy_tot += 1
            for j in range(i+1, min(i+51, len(df))):
                if df['high'].iloc[j] >= tp: buy_wins+=1; break
                elif df['low'].iloc[j] <= sl: break
        elif signal_sell:
            sell_tot += 1
            for j in range(i+1, min(i+51, len(df))):
                if df['low'].iloc[j] <= tp: sell_wins+=1; break
                elif df['high'].iloc[j] >= sl: break
                
    b_wr = (buy_wins/(buy_tot+0.001)*100); s_wr = (sell_wins/(sell_tot+0.001)*100)
    return b_wr, buy_tot, s_wr, sell_tot

def get_fibonacci_levels(df):
    recent_high = df['high'].tail(100).max()
    recent_low = df['low'].tail(100).min()
    if pd.isna(recent_high) or pd.isna(recent_low): return 0, 0, 0, 0
    diff = recent_high - recent_low
    return recent_high, recent_low, recent_high - diff*0.382, recent_high - diff*0.618

def find_breakout_retest(df):
    try:
        # Նայում ենք վերջին 100 մոմերը՝ առավելագույն Դիմադրություն (Resistance) գտնելու համար
        recent_data = df.iloc[-100:-5].copy() # Վերջին 5 մոմը չենք նայում, որպեսզի break-ը պարզ լինի
        res_level = recent_data['high'].max()
        
        # Ստուգում ենք արդյոք վերջին 5 մոմերից որևէ մեկը ծակել ու փակվել է Resistance-ից վերև (Breakout)
        breakout = False
        breakout_idx = 0
        for i in range(-5, -1):
            if df.iloc[i]['close'] > res_level and df.iloc[i-1]['close'] < res_level:
                breakout = True
                breakout_idx = i
                break
                
        if breakout:
            # Ստուգում ենք արդյոք վերջին փակված մոմը իջել և դիպչում է այդ նախկին գծին (Re-test)
            last_candle = df.iloc[-2]
            # Թույլատրելի շեղում Re-test գոտու համար (կախված ATR-ից կամ 0.2%)
            zone_tolerance = res_level * 0.002 
            
            if (last_candle['low'] <= res_level + zone_tolerance) and (last_candle['close'] >= res_level - zone_tolerance):
                # Համոզվում ենք որ RSI-ը շատ տաք չէ (օրինակ < 65)
                if last_candle['RSI_14'] < 65:
                    return True, res_level, "Breakout & Re-Test"
                    
        return False, 0, ""
    except Exception:
        return False, 0, ""

def check_signals(symbol, timeframe, btc_trend="NEUTRAL", fng_data=None, is_manual=False, chat_id=None):
    if not is_manual:
        for side in ['BUY', 'SELL']:
            last_t = SIGNAL_HISTORY.get((symbol, timeframe, side))
            if last_t and (time.time() - last_t < 4 * 3600):
                return
    try:
        df = get_data(symbol, timeframe, limit=1000)
        df = analyze_data(df)
        df.ta.ema(length=20, append=True) # Ensure EMA20 is available for trend alignment
        
        last_row = df.iloc[-2] 
        prev_row = df.iloc[-3]
        
        close = last_row['close']
        ema20 = last_row['EMA_20']
        ema50 = last_row['EMA_50']
        ema200 = last_row['EMA_200']
        rsi = last_row['RSI_14']
        macd = last_row['MACD_12_26_9']
        macd_signal = last_row['MACDs_12_26_9']
        lower_bb = last_row['BBL_20_2.0_2.0']
        upper_bb = last_row['BBU_20_2.0_2.0']
        atr = last_row['ATRr_14']

        signal = None
        trade_side = None
        signal_type = ""
        
        # Ստանում ենք BTC-ի Գլոբալ Տրենդը
        global_btc_trend = btc_trend
        
        # ԱՆԱԼԻԶ 1: TREND FOLLOWING (PULLBACK & CONTINUATION)
        # Փնտրում ենք առողջ տրենդներ (EMA20 > EMA50 > EMA200) և սպասում ժամանակավոր նահանջի
        
        # BUY (LONG) CONTINUATION STRATEGY
        is_uptrend = (ema20 > ema50) and (ema50 > ema200)
        # Գինը նահանջել է դեպի EMA20 կամ EMA50, բայց չի կոտրել EMA50-ը (Pullback)
        pullback_support = (last_row['low'] <= ema20 * 1.005) and (close >= ema50)
        # Բարձրացող մոմենտումի նշաններ (MACD Cross կամ RSI Bouncing)
        momentum_up = (macd > macd_signal) and (rsi > prev_row['RSI_14'])
        
        if is_uptrend and pullback_support and momentum_up:
            if global_btc_trend == "DOWNTREND": 
                if is_manual:
                    send_message(chat_id if chat_id else TELEGRAM_CHAT_IDS[0], f"⚠️ {symbol} ունի LONG սիգնալ, բայց արգելափակվեց (BTC Downtrend):")
            else:
                signal = "BUY 🟢 (LONG Trend)"
                trade_side = "BUY"
                signal_type = f"Trend Pullback + [BTC Տրենդ: {global_btc_trend}]"
                entry = close; sl = entry - (atr * 1.5); tp = entry + (atr * 3.0)
            
        # SELL (SHORT) CONTINUATION STRATEGY
        is_downtrend = (ema20 < ema50) and (ema50 < ema200)
        # Գինը բարձրացել է դեպի EMA20 կամ EMA50, բայց չի կոտրել EMA50-ը
        pullback_resist = (last_row['high'] >= ema20 * 0.995) and (close <= ema50)
        # Ընկնող մոմենտումի նշաններ
        momentum_down = (macd < macd_signal) and (rsi < prev_row['RSI_14'])
        
        if is_downtrend and pullback_resist and momentum_down:
            if global_btc_trend == "UPTREND": 
                if is_manual:
                    send_message(chat_id if chat_id else TELEGRAM_CHAT_IDS[0], f"⚠️ {symbol} ունի SHORT սիգնալ, բայց արգելափակվեց (BTC Uptrend):")
            else:
                signal = "SELL 🔴 (SHORT Trend)"
                trade_side = "SELL"
                signal_type = f"Trend Pullback + [BTC Տրենդ: {global_btc_trend}]"
                entry = close; sl = entry + (atr * 1.5); tp = entry - (atr * 3.0)
            
        # ԱՆԱԼԻԶ 2: PRICE ACTION (BREAKOUT & RE-TEST)
        if not signal:
            is_retest, retest_lvl, r_type = find_breakout_retest(df)
            if is_retest:
                # Breakout սիգնալների դեպքում նույնպես ստուգում ենք կոնտեքստը
                if global_btc_trend != "DOWNTREND":
                    signal = "BUY 🟢 (LONG)"
                    trade_side = "BUY"
                    signal_type = f"Price Action ({r_type}) + [BTC Տրենդ: {global_btc_trend}]"
                    entry = close
                    sl = entry - (atr * 1.2) # Re-test ների ստոպը ավելի մոտ ենք դնում
                    tp = entry + (atr * 3.5) # Վազքը ավելի մեծ է լինելու

        # Ֆիբոնաչիներ, Win-Rate, Էմոցիաներ և Order Book Պատեր (Կետեր)
        high, low, fib382, fib618 = get_fibonacci_levels(df)
        b_wr, b_tot, s_wr, s_tot = get_historical_winrate(df, mode='indicator')
        fng_val, fng_status = fng_data if fng_data else (None, "Անհայտ")
        walls_msg = check_order_book_walls(symbol, close)
        
        if signal:
            current_wr = b_wr if trade_side == 'BUY' else s_wr
            if current_wr < 50.0:
                if is_manual:
                    send_message(chat_id if chat_id else TELEGRAM_CHAT_IDS[0], f"⚠️ {symbol} ({timeframe}) ունի սիգնալ, բայց մերժվեց ցածր Win-Rate-ի պատճառով ({current_wr:.1f}%):")
                else:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] {symbol} ({timeframe}) - Սիգնալը մերժվեց ցածր Win-Rate-ի պատճառով ({current_wr:.1f}%):")
                return

            # ԾԱՎԱԼԻ ՖԻԼՏՐ (Volume Spike Check)
            if not is_volume_significant(df, threshold=1.5):
                if is_manual:
                    send_message(chat_id if chat_id else TELEGRAM_CHAT_IDS[0], f"⚠️ {symbol} ({timeframe}) ունի սիգնալ, բայց ԾԱՎԱԼԸ թույլ է (Volume Filter):")
                else:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] {symbol} ({timeframe}) - Սիգնալը մերժվեց ցածր ծավալի պատճառով:")
                return

            # == ADVANCED FEATURE 2: TRAILING STOP-LOSS ==
            trail_step = atr * 1.0  
            trail_dist = atr * 1.5  
            
            # TP1 և TP2 հաշվարկ (TP1-ը ընդհանուր շարժի 40%-ի վրա)
            tp1 = entry + (atr * 1.2) if trade_side == 'BUY' else entry - (atr * 1.2)
            tp2 = tp

            msg = f"🔔 *ԱԶԴԱՆՇԱՆ: {symbol}* ({timeframe})\n\n"
            msg += f"🔥 *Գործարք:* {signal}\n"
            msg += f"🧠 *Տրամաբանություն:* `{signal_type}`\n"
            msg += f"💵 *Մուտք (Entry):* `{entry:.4f}`\n\n"
            
            msg += f"🎯 *Take Profit 1:* `{tp1:.4f}` (Փակել 50%-ը)\n"
            msg += f"🎯 *Take Profit 2:* `{tp2:.4f}` (Վերջնական)\n"
            msg += f"🛑 *Stop Loss:* `{sl:.4f}`\n\n"
            
            msg += f"🛡 *ԱՆՎՏԱՆԳՈՒԹՅԱՆ ԿԱՆՈՆ:*\n"
            msg += f"Երբ գինը հասնի *TP1*-ին, անմիջապես տեղափոխիր քո Stop Loss-ը մուտքի գնի (`{entry:.4f}`) վրա: Սա կդարձնի գործարքը ԱՆՎՃԱՐ!\n\n"
            
            msg += f"🛡 *Trailing Stop (Լողացող Անվտանգություն):*\n"
            msg += f"• Պահիր քո StopLoss-ը շուկայական գնից `{trail_dist:.4f}` հեռավորության վրա, մինչև շուկան բերի մաքսիմալ շահույթ:\n\n"
            
            msg += f"📈 *Win-Rate:* `{(b_wr if trade_side=='BUY' else s_wr):.1f}%` (հիմնված {(b_tot if trade_side=='BUY' else s_tot)} սիգնալի վրա)\n"
            msg += f"🧠 *Շուկայի հոգեբանություն:* {fng_val}/100 - {fng_status}\n\n"
            
            funding = get_funding_rate(symbol)
            is_manipulated, manip_msg = check_manipulation(df)
            msg += "🌐 *ՇՈՒԿԱՅԱԿԱՆ ԿՈՆՏԵՔՍՏ:*\n"
            msg += f"• Funding Rate: `{funding*100:.4f}%` {'(High 🔴)' if abs(funding) > 0.0003 else '(Normal ✅)'}\n"
            if is_manipulated: msg += f"• Risk: `{manip_msg}`\n"
            msg += "\n"
            
            # Ավելացվում է նորագույն ապահովությունը
            msg += walls_msg
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Գտնվեց {signal} {symbol}-ի համար ({timeframe})")
            broadcast(msg)
            update_signal_history(symbol, timeframe, trade_side)
            record_signal(symbol, timeframe, trade_side)
            add_active_trade(symbol, entry, tp1, tp2, sl, trade_side)
        else:
            if is_manual:
                msg = f"📊 *Անալիզ: {symbol}* ({timeframe})\n\n"
                msg += "Գործարքի հստակ ՄՈՒՏՔԱՅԻՆ ազդանշան չկա այս պահին։ Համբերեք...\n\n"
                msg += f"📉 *Ինդիկատորներ:*\n"
                msg += f"• Գինը Հիմա: `{close:.4f}`\n"
                msg += f"• RSI: `{rsi:.1f}`\n"
                msg += f"• Տրենդ: `{'Աճող 🟢' if ema50 > ema200 else 'Նվազող 🔴'}`\n\n"
                msg += f"📏 *Դիմադրություն և Աջակցություն:*\n"
                msg += f"• Դիմադրություն (Max High): `{high:.4f}`\n"
                msg += f"• Ոսկե Fibo (0.618): `{fib618:.4f}`\n"
                msg += f"• Աջակցություն (Min Low): `{low:.4f}`\n\n"
                msg += f"🧠 *Շուկայի հոգեբանություն:* {fng_val}/100 - {fng_status}\n"
                msg += f"🌐 *BTC Գլոբալ Տրենդ (4h):* `{global_btc_trend}`\n\n"
                msg += walls_msg
                target_chat_id = chat_id if chat_id else TELEGRAM_CHAT_IDS[0]
                send_message(target_chat_id, msg)
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [{timeframe}] {symbol} - Ճշգրիտ մուտք չկա։")

    except Exception as e:
        print(f"Սխալ {symbol} ({timeframe}) տվյալների անալիզի ժամանակ: {e}")

# == ADVANCED SCALPING FEATURE: 3% Move Detection ==
def check_scalping_signals(symbol, timeframe, btc_trend="NEUTRAL", is_manual=False, chat_id=None):
    if not is_manual:
        for side in ['BUY', 'SELL']:
            last_t = SIGNAL_HISTORY.get((symbol, timeframe, side))
            if last_t and (time.time() - last_t < 30 * 60):
                return
    try:
        # Քաշում ենք ավելի շատ տվյալ Scalp-ի համար, որպեսզի Win-Rate-ը ունենա պատմություն
        df = get_data(symbol, timeframe, limit=500)
        df = analyze_data(df)
        last_row = df.iloc[-2] 
        prev_row = df.iloc[-3]
        
        # 1. VOLUME PROFILE CHECK
        vol_node = get_high_volume_node(df)
        
        # 2. 1H MACD CONFLUENCE CHECK
        try:
            df_1h = get_data(symbol, '1h', limit=50)
            df_1h.ta.macd(append=True)
            last_1h = df_1h.iloc[-2]
            macd_1h = last_1h['MACD_12_26_9']
            macd_signal_1h = last_1h['MACDs_12_26_9']
        except Exception:
            macd_1h = 0
            macd_signal_1h = 0 # Default if 1h fetch fails
        
        close = last_row['close']
        ema50 = last_row['EMA_50']
        rsi = last_row['RSI_14']
        macd = last_row['MACD_12_26_9']
        macd_signal = last_row['MACDs_12_26_9']
        lower_bb = last_row['BBL_20_2.0_2.0']
        upper_bb = last_row['BBU_20_2.0_2.0']
        atr = last_row['ATRr_14']

        # Մենք փնտրում ենք պոտենցիալ շարժ։
        # Իջեցված շեմ՝ 0.8% (0.008), որպեսզի բոտը ավելի հաճախ սիգնալ տա սովորական շուկայում:
        if (atr * 3) / close < 0.008: 
            if is_manual:
                target_chat_id = chat_id if chat_id else TELEGRAM_CHAT_IDS[0]
                send_message(target_chat_id, f"📊 *Scalp Անալիզ: {symbol}* ({timeframe})\n\nՇուկան շատ \"քնած\" է: Վոլատիլությունը ցածր է 3% շարժի համար:")
            return # Բավարար էներգիա չկա պոտենցիալ 3% շարժի համար

        signal = None
        trade_side = None
        
        # BUY (LONG) SCALP STRATEGY:
        # Մեղմացված պայմաններ. Bollinger + RSI միայն (առանց MACD)
        if (last_row['low'] <= lower_bb or prev_row['low'] <= prev_row['BBL_20_2.0_2.0']) and \
           (rsi > prev_row['RSI_14'] and rsi < 45):
           
            # TREND FILTER: Եթե BTC-ն DOWNTREND է, LONG չենք մտնում
            if btc_trend == "DOWNTREND":
                if is_manual:
                    send_message(chat_id if chat_id else TELEGRAM_CHAT_IDS[0], f"⚠️ {symbol} LONG Scalp-ը մերժվեց, քանի որ BTC-ն DOWNTREND է:")
                return

            # LOCAL TREND FILTER: Եթե գինը EMA50-ից ներքև է, պետք չէ «ընկնող դանակ» բռնել
            if close < ema50:
                if is_manual:
                    send_message(chat_id if chat_id else TELEGRAM_CHAT_IDS[0], f"⚠️ {symbol} LONG Scalp-ը մերժվեց, քանի որ գինը EMA50-ից ներքև է (Local Trend):")
                return

            # 1H CONFLUENCE (LONG): 1-ժամյա MACD-ն պետք է լինի աճող (MACD > Signal)
            if macd_1h <= macd_signal_1h:
                if is_manual:
                    send_message(chat_id if chat_id else TELEGRAM_CHAT_IDS[0], f"⚠️ {symbol} LONG Scalp-ը մերժվեց, քանի որ 1h MACD-ն աճող չէ (Confluence Failure):")
                return
                
            # VOLUME PROFILE FILTER (LONG): Գինը պետք է լինի ուժեղ Volume Node-ի մակարդակում կամ դրանից ներքև (հանդիպում է աջակցության)
            if close > vol_node * 1.005:  # Թույլտվություն ձգտման համար (0.5% տոլերանտություն)
                if is_manual:
                    send_message(chat_id if chat_id else TELEGRAM_CHAT_IDS[0], f"⚠️ {symbol} LONG Scalp-ը մերժվեց, քանի որ մոտակայքում բարձր ծավալով հենարան (support) չկա:")
                return

            signal = "BUY 🟢 (LONG SCALP)"
            trade_side = "BUY"
            entry = close
            sl = entry * 0.992 # 0.8% SL
            tp = entry * 1.008 # 0.8% TP
            sl_percent = 0.8

        # SELL (SHORT) SCALP STRATEGY:
        elif (last_row['high'] >= upper_bb or prev_row['high'] >= prev_row['BBU_20_2.0_2.0']) and \
             (rsi < prev_row['RSI_14'] and rsi > 55):
             
            # TREND FILTER: Եթե BTC-ն UPTREND է, SHORT չենք մտնում
            if btc_trend == "UPTREND":
                if is_manual:
                    send_message(chat_id if chat_id else TELEGRAM_CHAT_IDS[0], f"⚠️ {symbol} SHORT Scalp-ը մերժվեց, քանի որ BTC-ն UPTREND է:")
                return

            # LOCAL TREND FILTER: Եթե գինը EMA50-ից վերև է, SHORT-ը վտանգավոր է
            if close > ema50:
                if is_manual:
                    send_message(chat_id if chat_id else TELEGRAM_CHAT_IDS[0], f"⚠️ {symbol} SHORT Scalp-ը մերժվեց, քանի որ գինը EMA50-ից վերև է (Local Trend):")
                return

            # 1H CONFLUENCE (SHORT): 1-ժամյա MACD-ն պետք է լինի նվազող (MACD < Signal)
            if macd_1h >= macd_signal_1h:
                if is_manual:
                    send_message(chat_id if chat_id else TELEGRAM_CHAT_IDS[0], f"⚠️ {symbol} SHORT Scalp-ը մերժվեց, քանի որ 1h MACD-ն աճող է (Confluence Failure):")
                return

            # VOLUME PROFILE FILTER (SHORT): Գինը պետք է լինի ուժեղ Volume Node-ի մակարդակում կամ դրանից վերև (հանդիպում է դիմադրության)
            if close < vol_node * 0.995: # Թույլտվություն (0.5% տոլերանտություն)
                if is_manual:
                    send_message(chat_id if chat_id else TELEGRAM_CHAT_IDS[0], f"⚠️ {symbol} SHORT Scalp-ը մերժվեց, քանի որ մոտակայքում բարձր ծավալով դիմադրություն չկա:")
                return

            signal = "SELL 🔴 (SHORT SCALP)"
            trade_side = "SELL"
            entry = close
            sl = entry * 1.008 # 0.8% SL
            tp = entry * 0.992 # 0.8% TP
            sl_percent = 0.8
            
        if signal:
            # ԾԱՎԱԼԻ ՖԻԼՏՐ (Volume Spike Check)
            if not is_volume_significant(df, threshold=1.5):
                if is_manual:
                    send_message(chat_id if chat_id else TELEGRAM_CHAT_IDS[0], f"⚠️ SCALP: {symbol} ({timeframe}) ունի սիգնալ, բայց ԾԱՎԱԼԸ թույլ է:")
                else:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] SCALP {symbol} ({timeframe}) - Մերժվեց ցածր ծավալի պատճառով:")
                return

            b_wr, b_tot, s_wr, s_tot = get_historical_winrate(df, mode='scalp')
            
            current_wr = b_wr if trade_side == 'BUY' else s_wr
            if current_wr < 50.0:
                if is_manual:
                    send_message(chat_id if chat_id else TELEGRAM_CHAT_IDS[0], f"⚠️ SCALP: {symbol} ({timeframe}) ունի սիգնալ, բայց մերժվեց ցածր Win-Rate-ի պատճառով ({current_wr:.1f}%):")
                else:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] SCALP {symbol} ({timeframe}) - Մերժվեց ցածր Win-Rate-ի պատճառով ({current_wr:.1f}%):")
                return
            
            # TP1 և TP2 հաշվարկ Scalp-ի համար (TP1 = 0.4%, TP2 = 0.8%)
            tp1 = entry * 1.004 if trade_side == 'BUY' else entry * 0.996
            tp2 = tp

            msg = f"⚡ *ԱՐԱԳ SCALP ՍԻԳՆԱԼ: {symbol}* ({timeframe})\n\n"
            msg += f"🎯 *Սպասվող Շարժը: 0.8%+*\n"
            msg += f"🔥 *Գործարք:* {signal}\n"
            msg += f"💵 *Մուտք (Entry):* `{entry:.4f}`\n\n"
            msg += f"✅ *Take Profit 1:* `{tp1:.4f}` (0.4%)\n"
            msg += f"✅ *Take Profit 2:* `{tp2:.4f}` (0.8%)\n"
            msg += f"🛑 *Stop Loss:* `{sl:.4f}` (-{sl_percent:.2f}%)\n\n"
            
            msg += f"🛡 *ԿԱՆՈՆ:* TP1-ին հասնելիս SL-ը տեղափոխիր *Entry*!\n\n"
            
            msg += f"📈 *Win-Rate:* `{(b_wr if trade_side=='BUY' else s_wr):.1f}%` (հիմնված {(b_tot if trade_side=='BUY' else s_tot)} սիգնալի վրա)\n"
            
            funding = get_funding_rate(symbol)
            is_manipulated, manip_msg = check_manipulation(df)
            msg += f"🌐 Funding: `{funding*100:.4f}%` {'⚠️' if abs(funding) > 0.0003 else '✅'}\n"
            if is_manipulated: msg += f"🚨 {manip_msg}\n"
            
            msg += f"\n🧠 *Ինչու՞:* Bollinger Band ցատկ & RSI շրջադարձ (Scalp mode)։"
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Գտնվեց SCALP {signal} {symbol}-ի համար ({timeframe})")
            broadcast(msg)
            record_signal(symbol, timeframe, trade_side)
        else:
            if is_manual:
                msg = f"📊 *Scalp Անալիզ: {symbol}* ({timeframe})\n\n"
                msg += "Այս պահին Scalp (արագ) մուտքի հստակ պայմաններ չկան (RSI, BB կամ MACD ցուցանիշները չեն համապատասխանում խիստ կանոններին)։\n"
                msg += f"Գինը Հիմա. `{close:.4f}`\n"
                target_chat_id = chat_id if chat_id else TELEGRAM_CHAT_IDS[0]
                send_message(target_chat_id, msg)
            
    except Exception as e:
        print(f"Սխալ {symbol} ({timeframe}) Scalping անալիզի ժամանակ: {e}")

def check_pump_dump():
    try:
        btc_trend = get_btc_global_trend()
        fng_val, fng_status = get_fear_and_greed_index()
        
        for symbol in SYMBOLS:
            try:
                # Քաշում ենք 5m տվյալներ
                bars = exchange.fetch_ohlcv(symbol, '5m', limit=100)
                df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                
                # Ավելացնում ենք ինդիկատորներ (RSI)
                df.ta.rsi(length=14, append=True)
                
                last_candle = df.iloc[-2] 
                prev_candles = df.iloc[-12:-2]
                
                avg_vol = prev_candles['volume'].mean() + 0.001
                vol = last_candle['volume']
                open_p = last_candle['open']
                close_p = last_candle['close']
                rsi = last_candle.get('RSI_14', 50)
                
                price_change = ((close_p - open_p) / open_p) * 100
                
                # Pump/Dump Detection Logic (2.5x Volume & 1.5% Price Change)
                if vol > (avg_vol * 2.5) and abs(price_change) >= 1.5:
                    direction = "🚀 PUMP (ԱՃ)" if price_change > 0 else "🩸 DUMP (ԱՆԿՈՒՄ)"
                    side = "BUY" if price_change > 0 else "SELL"
                    
                    # Լրացուցիչ Ֆիլտրեր
                    warning_msg = ""
                    
                    if side == "BUY":
                        if btc_trend == "DOWNTREND":
                            warning_msg += "⚠️ *ԶԳՈՒՇԱՑՈՒՄ:* BTC-ն անկման մեջ է (Downtrend), այս Pump-ը կարող է կեղծ լինել!\n"
                        if rsi > 80:
                            warning_msg += "🔥 *ԳԵՐՏԱՔԱՑԱԾ:* RSI-ն շատ բարձր է (>80), հավանական է շուտով հետադարձ (Retrace):\n"
                    else: # SELL/DUMP
                        if btc_trend == "UPTREND":
                            warning_msg += "⚠️ *ԶԳՈՒՇԱՑՈՒՄ:* BTC-ն աճի մեջ է (Uptrend), այս Dump-ը կարող է արագ հետ գնվել!\n"
                        if rsi < 20:
                            warning_msg += "🧊 *ԳԵՐՎԱՃԱՌՎԱԾ:* RSI-ն շատ ցածր է (<20), հավանական է շուտով թռիչք դեպի վերև:\n"

                    # Թիրախների և Աջակցության հաշվարկ (Fibonacci)
                    high_100 = df['high'].max()
                    low_100 = df['low'].min()
                    diff = high_100 - low_100
                    
                    support_line = close_p - (abs(price_change)/100 * close_p * 0.5) # Շարժի կեսը որպես աջակցություն
                    target_1 = close_p + (diff * 0.236) if side == "BUY" else close_p - (diff * 0.236)
                    
                    # Order Book Walls Check
                    walls_msg = check_order_book_walls(symbol, close_p)
                    
                    msg = f"🚨 *{direction} ԱՀԱԶԱՆԳ: {symbol}*\n\n"
                    msg += f"📊 *Շարժը:* `{price_change:.2f}%` (5 րոպեում)\n"
                    msg += f"💵 *Գինը Հիմա:* `{close_p:.4f}`\n"
                    msg += f"🌊 *RSI:* `{rsi:.1f}`\n\n"
                    
                    if warning_msg:
                        msg += f"{warning_msg}\n"
                    
                    msg += f"🛡 *Աջակցության գիծ:* `{support_line:.4f}` (Եթե իջնի սրանից ներքև՝ կեղծ է)\n"
                    msg += f"🎯 *Հնարավոր Թիրախ:* `{target_1:.4f}`\n\n"
                    
                    msg += f"🌐 *BTC Տրենդ (4h):* `{btc_trend}`\n"
                    msg += f"🧠 *Շուկայի վիճակ:* {fng_val} - {fng_status}\n\n"
                    
                    msg += f"🐋 *Order Book Անալիզ:*\n{walls_msg}"
                    
                    broadcast(msg)
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] {direction} հայտնաբերվեց: {symbol}")
                    
            except Exception as e:
                print(f"Սխալ {symbol} Pump/Dump ստուգման ժամանակ: {e}")
    except Exception as e:
        print(f"Սխալ check_pump_dump հիմնական loop-ում: {e}")

def poll_telegram():
    last_update_id = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?timeout=10&offset={last_update_id}"
            resp = requests.get(url, timeout=15).json()
            if resp.get('ok'):
                for update in resp['result']:
                    last_update_id = update['update_id'] + 1
                    if 'message' in update and 'text' in update['message']:
                        chat_id = str(update['message']['chat']['id'])
                        text = update['message']['text']
                        
                        if chat_id not in TELEGRAM_CHAT_IDS:
                            continue
                            
                        if text == '/status':
                            f_val, f_stat = get_fear_and_greed_index()
                            msg = "✅ *Բոտը Ակտիվ է և Աշխատում է:*\n"
                            msg += f"Հետևվող Ակտիվներ. {', '.join([s.split('/')[0] for s in SYMBOLS])}\n"
                            msg += f"🧠 Շուկա: {f_val} - {f_stat}\n"
                            msg += f"🐋 OrderBook Heatmap: `Ակտիվ`"
                            send_message(chat_id, msg)
                        elif text.startswith('/analyze'):
                            parts = text.split()
                            if len(parts) > 1:
                                sym = parts[1].upper()
                                if 'USDT' not in sym: sym += '/USDT'
                                send_message(chat_id, f"⏳ {sym}-ի ակնթարթային Advanced անալիզ է արվում...")
                                check_signals(sym, '1h', is_manual=True, chat_id=chat_id)
                            else:
                                send_message(chat_id, "Օրինակ՝ գրեք `/analyze SOL` կամ `/analyze BNB`")
                        elif text.startswith('/scalp'):
                            parts = text.split()
                            if len(parts) > 1:
                                sym = parts[1].upper()
                                if 'USDT' not in sym: sym += '/USDT'
                                send_message(chat_id, f"⚡ {sym}-ի արագ Scalp անալիզ է արվում (15m)...")
                                check_scalping_signals(sym, '15m', is_manual=True, chat_id=chat_id)
                            else:
                                send_message(chat_id, "Օրինակ՝ գրեք `/scalp SOL` կամ `/scalp BNB`")
        except Exception:
            time.sleep(5)

import sys

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding='utf-8')
    os.system('cls' if os.name == 'nt' else 'clear')
    print("🤖 CryptoBot EXPERT Միացված է...\n")
    
    # Start Keep Alive server in a separate thread
    threading.Thread(target=run_keep_alive, daemon=True).start()
    
    threading.Thread(target=poll_telegram, daemon=True).start()
    threading.Thread(target=monitor_active_trades, daemon=True).start()
    
    broadcast("🤖 *CryptoBot EXPERT միացավ:*\n\nՆոր Հնարավորություններ.\n1️⃣ *Fear & Greed Index* սեկտոր\n2️⃣ *Trailing Stop-Loss*\n3️⃣ *Order Book Walls* (Կետերի Որոնում)\n4️⃣ *ՆՈՐ: 3%+ Scalping Ռազմավարություն* ⚡\n5️⃣ *Օրական Ամփոփագիր* 📊\n\n💬 Գրիր /status, /analyze ETH կամ /scalp ETH")
    
    analysis_interval = 15 * 60 
    pump_interval = 5 * 60      
    scalp_interval = 5 * 60     # Scalp checks every 5 minutes
    report_interval = 24 * 60 * 60 # Daily report every 24 hours
    
    last_analysis = 0
    last_pump_check = 0
    last_scalp_check = 0
    last_report_time = time.time()
    
    while True:
        try:
            current_time = time.time()
            if current_time - last_pump_check >= pump_interval:
                check_pump_dump()
                last_pump_check = current_time

            # SCALPING CHECK
            if current_time - last_scalp_check >= scalp_interval:
                print(f"\n--- [{datetime.now().strftime('%H:%M:%S')}] Սկսվում է Սկալպինգի Արագ Ստուգումը (Multithreaded) ---")
                for timeframe in SCALPING_TIMEFRAMES:
                    with ThreadPoolExecutor(max_workers=5) as executor:
                        futures = [executor.submit(check_scalping_signals, symbol, timeframe) for symbol in SYMBOLS]
                        for future in as_completed(futures):
                            try:
                                future.result()
                            except Exception as e:
                                print(f"Սխալ Thread-ում: {e}")
                last_scalp_check = current_time
                print("⚡ Սկալպինգի ստուգումն ավարտվեց։")
                
            if current_time - last_analysis >= analysis_interval or last_analysis == 0:
                print(f"\n--- [{datetime.now().strftime('%H:%M:%S')}] Սկսվում է Գլոբալ Անալիզը (Multithreaded) ---")
                
                # Cache BTC trend and Fear & Greed ONCE per cycle
                current_btc_trend = get_btc_global_trend()
                current_fng = get_fear_and_greed_index()
                
                for timeframe in TIMEFRAMES:
                    with ThreadPoolExecutor(max_workers=5) as executor:
                        futures = [executor.submit(check_signals, symbol, timeframe, current_btc_trend, current_fng) for symbol in SYMBOLS]
                        for future in as_completed(futures):
                            try:
                                future.result()
                            except Exception as e:
                                print(f"Սխալ Thread-ում: {e}")
                last_analysis = time.time()
                print("⏳ Բոլորը ստուգված են։ Շարունակվում է ֆոնային վերահսկումը...")

            # DAILY REPORT CHECK
            if current_time - last_report_time >= report_interval:
                print(f"\n--- [{datetime.now().strftime('%H:%M:%S')}] Ուղարկվում է Օրական Հաշվետվությունը ---")
                send_daily_report()
                last_report_time = current_time
                
            time.sleep(10) 
            
        except KeyboardInterrupt:
            print("\nԲոտը կանգնեցվել է ձեռքով։")
            break
