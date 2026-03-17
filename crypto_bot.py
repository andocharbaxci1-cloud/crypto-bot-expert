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

# ================= ԳԼՈԲԱԼ ՓՈՓՈԽԱԿԱՆՆԵՐ =================
BOT_START_TIME = datetime.now()
COMMAND_EXECUTOR = ThreadPoolExecutor(max_workers=10) # Հրամանների համար առանձին executor
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
        avg_vol = df['volume'].iloc[-period-1:-1].mean()
        current_vol = df['volume'].iloc[-2] # Վերջին փակված մոմը
        return current_vol >= (avg_vol * threshold) if avg_vol > 0 else True
    except Exception:
        return True

def get_high_volume_node(df, lookback_candles=100, bins=20):
    try:
        recent_df = df.iloc[-lookback_candles-2:-2].copy()
        if recent_df.empty: return 0
        min_p = recent_df['low'].min()
        max_p = recent_df['high'].max()
        if min_p == max_p: return min_p
        bin_size = (max_p - min_p) / bins
        volume_profile = {}
        for i in range(bins):
            volume_profile[min_p + (i * bin_size)] = 0
        for _, row in recent_df.iterrows():
            avg_price = (row['high'] + row['low'] + row['close']) / 3
            closest_bin = min(volume_profile.keys(), key=lambda k: abs(k - avg_price))
            volume_profile[closest_bin] += row['volume']
        high_volume_node = max(volume_profile, key=volume_profile.get)
        return high_volume_node
    except Exception:
        return 0

def log(message):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")

def send_message(chat_id, text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}, timeout=15)
    except Exception as e:
        log(f"Սխալ նամակ ուղարկելիս: {e}")

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
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# == ADVANCED FEATURE 1: FEAR & GREED INDEX ==
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

# == ADVANCED FEATURE 4: ORDER BOOK HEATMAP ==
def check_order_book_walls(symbol, current_price):
    try:
        order_book = exchange.fetch_order_book(symbol, limit=50)
        bids = order_book['bids']
        asks = order_book['asks']
        max_bid = max(bids, key=lambda x: x[1]) if bids else [0, 0]
        max_ask = max(asks, key=lambda x: x[1]) if asks else [0, 0]
        wall_msg = ""
        sum_bids_vol = sum(vol for price, vol in bids)
        sum_asks_vol = sum(vol for price, vol in asks)
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
                if msg: broadcast(msg)
                if not remove: updated_trades.append(t)
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

def get_btc_global_trend():
    try:
        df_4h = get_data('BTC/USDT', '4h', limit=250)
        df_4h.ta.ema(length=50, append=True)       
        df_4h.ta.ema(length=200, append=True)
        last_4h = df_4h.iloc[-2]
        slow_trend = "NEUTRAL"
        if last_4h['close'] > last_4h['EMA_200'] and last_4h['EMA_50'] > last_4h['EMA_200']:
            slow_trend = "UPTREND"
        elif last_4h['close'] < last_4h['EMA_200'] and last_4h['EMA_50'] < last_4h['EMA_200']:
            slow_trend = "DOWNTREND"
        df_1h = get_data('BTC/USDT', '1h', limit=100)
        df_1h.ta.ema(length=20, append=True)
        df_1h.ta.ema(length=50, append=True)
        last_1h = df_1h.iloc[-2]
        fast_trend = "NEUTRAL"
        if last_1h['close'] > last_1h['EMA_50'] and last_1h['EMA_20'] > last_1h['EMA_50']:
            fast_trend = "UPTREND"
        elif last_1h['close'] < last_1h['EMA_50'] and last_1h['EMA_20'] < last_1h['EMA_50']:
            fast_trend = "DOWNTREND"
        if fast_trend == "UPTREND": return "UPTREND"
        elif slow_trend == "UPTREND" and fast_trend == "DOWNTREND": return "NEUTRAL"
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
        prev_rs = df['RSI_14'].iloc[i-1]
        signal_buy = False; signal_sell = False
        if mode == 'indicator':
            is_uptrend = (e20 > e50) and (e50 > e200)
            pullback_supp = (low_i <= e20 * 1.005) and (c >= e50)
            mom_up = (mac > mac_s) and (rs > prev_rs)
            if is_uptrend and pullback_supp and mom_up:
                signal_buy = True; tp = c + (at*3.0); sl = c - (at*1.5)
            is_downtrend = (e20 < e50) and (e50 < e200)
            pullback_res = (high_i >= e20 * 0.995) and (c <= e50)
            mom_down = (mac < mac_s) and (rs < prev_rs)
            if is_downtrend and pullback_res and mom_down:
                signal_sell = True; tp = c - (at*3.0); sl = c + (at*1.5)
        elif mode == 'scalp':
            if (low_i <= l_bb) and (rs > prev_rs and rs < 45):
                signal_buy = True; tp = c * 1.008; sl = c * 0.992
            elif (high_i >= u_bb) and (rs < prev_rs and rs > 55):
                signal_sell = True; tp = c * 0.992; sl = c * 1.008
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
        recent_data = df.iloc[-100:-5].copy()
        res_level = recent_data['high'].max()
        breakout = False
        for i in range(-5, -1):
            if df.iloc[i]['close'] > res_level and df.iloc[i-1]['close'] < res_level:
                breakout = True; break
        if breakout:
            last_candle = df.iloc[-2]
            zone_tolerance = res_level * 0.002 
            if (last_candle['low'] <= res_level + zone_tolerance) and (last_candle['close'] >= res_level - zone_tolerance):
                if last_candle['RSI_14'] < 65: return True, res_level, "Breakout & Re-Test"
        return False, 0, ""
    except Exception: return False, 0, ""

def check_signals(symbol, timeframe, btc_trend="NEUTRAL", fng_data=None, is_manual=False, chat_id=None):
    if not is_manual:
        for side in ['BUY', 'SELL']:
            last_t = SIGNAL_HISTORY.get((symbol, timeframe, side))
            if last_t and (time.time() - last_t < 4 * 3600): return
    try:
        df = get_data(symbol, timeframe, limit=1000)
        df = analyze_data(df)
        df.ta.ema(length=20, append=True)
        last_row = df.iloc[-2]; prev_row = df.iloc[-3]
        close = last_row['close']; ema20 = last_row['EMA_20']; ema50 = last_row['EMA_50']; ema200 = last_row['EMA_200']
        rsi = last_row['RSI_14']; macd = last_row['MACD_12_26_9']; macd_signal = last_row['MACDs_12_26_9']
        atr = last_row['ATRr_14']
        signal = None; trade_side = None; signal_type = ""
        global_btc_trend = btc_trend
        is_uptrend = (ema20 > ema50) and (ema50 > ema200)
        pullback_support = (last_row['low'] <= ema20 * 1.005) and (close >= ema50)
        momentum_up = (macd > macd_signal) and (rsi > prev_row['RSI_14'])
        if is_uptrend and pullback_support and momentum_up:
            if global_btc_trend == "DOWNTREND":
                if is_manual: send_message(chat_id, f"⚠️ {symbol} LONG blocked by BTC Downtrend")
            else:
                signal = "BUY 🟢 (LONG Trend)"; trade_side = "BUY"
                signal_type = f"Pullback + {global_btc_trend}"; entry = close; sl = entry - (atr * 1.5); tp = entry + (atr * 3.0)
        is_downtrend = (ema20 < ema50) and (ema50 < ema200)
        pullback_resist = (last_row['high'] >= ema20 * 0.995) and (close <= ema50)
        momentum_down = (macd < macd_signal) and (rsi < prev_row['RSI_14'])
        if is_downtrend and pullback_resist and momentum_down:
            if global_btc_trend == "UPTREND":
                if is_manual: send_message(chat_id, f"⚠️ {symbol} SHORT blocked by BTC Uptrend")
            else:
                signal = "SELL 🔴 (SHORT Trend)"; trade_side = "SELL"
                signal_type = f"Pullback + {global_btc_trend}"; entry = close; sl = entry + (atr * 1.5); tp = entry - (atr * 3.0)
        if not signal:
            is_retest, retest_lvl, r_type = find_breakout_retest(df)
            if is_retest and global_btc_trend != "DOWNTREND":
                signal = "BUY 🟢 (LONG)"; trade_side = "BUY"; signal_type = f"Price Action ({r_type}) + {global_btc_trend}"
                entry = close; sl = entry - (atr * 1.2); tp = entry + (atr * 3.5)
        high, low, fib382, fib618 = get_fibonacci_levels(df)
        b_wr, b_tot, s_wr, s_tot = get_historical_winrate(df, mode='indicator')
        fng_val, fng_status = fng_data if fng_data else (None, "Անհայտ")
        walls_msg = check_order_book_walls(symbol, close)
        if signal:
            current_wr = b_wr if trade_side == 'BUY' else s_wr
            if current_wr < 50.0:
                if is_manual: send_message(chat_id, f"⚠️ {symbol} low winrate {current_wr:.1f}%")
                return
            if not is_volume_significant(df): return
            tp1 = entry + (atr * 1.2) if trade_side == 'BUY' else entry - (atr * 1.2); tp2 = tp
            msg = f"🔔 *ԱԶԴԱՆՇԱՆ: {symbol}* ({timeframe})\n🔥 {signal}\n🧠 `{signal_type}`\n💵 Entry: `{entry:.4f}`\n🎯 TP1: `{tp1:.4f}`\n🎯 TP2: `{tp2:.4f}`\n🛑 SL: `{sl:.4f}`\n📈 WR: `{current_wr:.1f}%`\n" + walls_msg
            broadcast(msg)
            if is_manual and chat_id not in TELEGRAM_CHAT_IDS: send_message(chat_id, msg)
            update_signal_history(symbol, timeframe, trade_side)
            record_signal(symbol, timeframe, trade_side)
            add_active_trade(symbol, entry, tp1, tp2, sl, trade_side)
        elif is_manual:
            msg = f"📊 *Անալիզ: {symbol}* ({timeframe})\nԳործարքի հստակ ՄՈՒՏՔԱՅԻՆ ազդանշան չկա։\n" + walls_msg
            send_message(chat_id, msg)
    except Exception as e: log(f"Error analyzing {symbol}: {e}")

def check_scalping_signals(symbol, timeframe, btc_trend="NEUTRAL", is_manual=False, chat_id=None):
    if not is_manual:
        for side in ['BUY', 'SELL']:
            last_t = SIGNAL_HISTORY.get((symbol, timeframe, side))
            if last_t and (time.time() - last_t < 30 * 60): return
    try:
        df = get_data(symbol, timeframe, limit=500); df = analyze_data(df)
        last_row = df.iloc[-2]; prev_row = df.iloc[-3]; vol_node = get_high_volume_node(df)
        close = last_row['close']; ema50 = last_row['EMA_50']; rsi = last_row['RSI_14']; lower_bb = last_row['BBL_20_2.0_2.0']; upper_bb = last_row['BBU_20_2.0_2.0']; atr = last_row['ATRr_14']
        if (atr * 3) / close < 0.008:
            if is_manual: send_message(chat_id, f"📊 {symbol} low volatility")
            return
        signal = None; trade_side = None
        if (last_row['low'] <= lower_bb) and (rsi > prev_row['RSI_14'] and rsi < 45):
            if btc_trend != "DOWNTREND" and close >= ema50:
                signal = "BUY 🟢 (LONG SCALP)"; trade_side = "BUY"; entry = close; sl = entry * 0.992; tp = entry * 1.008; sl_percent = 0.8
        elif (last_row['high'] >= upper_bb) and (rsi < prev_row['RSI_14'] and rsi > 55):
            if btc_trend != "UPTREND" and close <= ema50:
                signal = "SELL 🔴 (SHORT SCALP)"; trade_side = "SELL"; entry = close; sl = entry * 1.008; tp = entry * 0.992; sl_percent = 0.8
        if signal:
            if not is_volume_significant(df): return
            b_wr, b_tot, s_wr, s_tot = get_historical_winrate(df, mode='scalp')
            current_wr = b_wr if trade_side == 'BUY' else s_wr
            if current_wr < 50.0: return
            tp1 = entry * 1.004 if trade_side == 'BUY' else entry * 0.996; tp2 = tp
            msg = f"⚡ *SCALP: {symbol}* ({timeframe})\n🔥 {signal}\n💵 Entry: `{entry:.4f}`\n🎯 TP1: `{tp1:.4f}`\n🎯 TP2: `{tp2:.4f}`\n🛑 SL: `{sl:.4f}`\n📈 WR: `{current_wr:.1f}%`"
            broadcast(msg)
            if is_manual and chat_id not in TELEGRAM_CHAT_IDS: send_message(chat_id, msg)
            record_signal(symbol, timeframe, trade_side)
        elif is_manual: send_message(chat_id, f"📊 Scalp {symbol}: No signal")
    except Exception as e: log(f"Scalp error {symbol}: {e}")

def check_pump_dump():
    try:
        btc_trend = get_btc_global_trend(); fng_v, fng_s = get_fear_and_greed_index()
        for symbol in SYMBOLS:
            try:
                bars = exchange.fetch_ohlcv(symbol, '5m', limit=100)
                df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df.ta.rsi(length=14, append=True); last = df.iloc[-2]; prev = df.iloc[-12:-2]
                avg_vol = prev['volume'].mean() + 0.001; vol = last['volume']; open_p = last['open']; close_p = last['close']; rsi = last.get('RSI_14', 50)
                price_change = ((close_p - open_p) / open_p) * 100
                if vol > (avg_vol * 2.5) and abs(price_change) >= 1.5:
                    direction = "🚀 PUMP" if price_change > 0 else "🩸 DUMP"; side = "BUY" if price_change > 0 else "SELL"
                    msg = f"🚨 *{direction}: {symbol}*\n📊 Change: `{price_change:.2f}%`\n💵 Price: `{close_p:.4f}`\n🌊 RSI: `{rsi:.1f}`\n" + check_order_book_walls(symbol, close_p)
                    broadcast(msg); log(f"{direction} detected: {symbol}")
            except: pass
    except: pass

def handle_command(chat_id, text):
    try:
        if text == '/status':
            f_v, f_s = get_fear_and_greed_index(); uptime = datetime.now() - BOT_START_TIME
            send_message(chat_id, f"✅ *Active*\n⏱ Uptime: `{uptime}`\n📊 Assets: {len(SYMBOLS)}\n🧠 Market: {f_v} - {f_s}")
        elif text.startswith('/analyze'):
            sym = text.split()[1].upper() if len(text.split())>1 else None
            if sym:
                if 'USDT' not in sym: sym += '/USDT'
                send_message(chat_id, f"⏳ Analyzing {sym}...")
                check_signals(sym, '1h', is_manual=True, chat_id=chat_id)
            else: send_message(chat_id, "Usage: /analyze SOL")
        elif text.startswith('/scalp'):
            sym = text.split()[1].upper() if len(text.split())>1 else None
            if sym:
                if 'USDT' not in sym: sym += '/USDT'
                send_message(chat_id, f"⚡ Scalping {sym}...")
                check_scalping_signals(sym, '15m', is_manual=True, chat_id=chat_id)
            else: send_message(chat_id, "Usage: /scalp SOL")
    except Exception as e: log(f"Command error ({text}): {e}")

def poll_telegram():
    last_update_id = 0; log("Polling started...")
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?timeout=10&offset={last_update_id}"
            resp = requests.get(url, timeout=20).json()
            if resp.get('ok'):
                for update in resp['result']:
                    last_update_id = update['update_id'] + 1
                    if 'message' in update and 'text' in update['message']:
                        chat_id = str(update['message']['chat']['id'])
                        if chat_id in TELEGRAM_CHAT_IDS:
                            COMMAND_EXECUTOR.submit(handle_command, chat_id, update['message']['text'])
        except Exception as e: log(f"Poll error: {e}"); time.sleep(10)

if __name__ == "__main__":
    os.system('cls' if os.name == 'nt' else 'clear'); log("Bot Starting...")
    threading.Thread(target=run_keep_alive, daemon=True).start()
    threading.Thread(target=poll_telegram, daemon=True).start()
    threading.Thread(target=monitor_active_trades, daemon=True).start()
    broadcast("🤖 *CryptoBot EXPERT Online*\nFeatures: Fear & Greed, Trailing SL, Order Book Walls, Scalping")
    l_analysis = 0; l_pump = 0; l_scalp = 0; l_report = time.time()
    while True:
        try:
            curr = time.time()
            if curr - l_pump >= 300: check_pump_dump(); l_pump = curr
            if curr - l_scalp >= 300:
                for tf in SCALPING_TIMEFRAMES:
                    with ThreadPoolExecutor(max_workers=5) as ex:
                        [ex.submit(check_scalping_signals, s, tf) for s in SYMBOLS]
                l_scalp = curr
            if curr - l_analysis >= 900:
                trend = get_btc_global_trend(); fng = get_fear_and_greed_index()
                for tf in TIMEFRAMES:
                    with ThreadPoolExecutor(max_workers=5) as ex:
                        [ex.submit(check_signals, s, tf, trend, fng) for s in SYMBOLS]
                l_analysis = curr
            if curr - l_report >= 86400: send_daily_report(); l_report = curr
            time.sleep(10)
        except KeyboardInterrupt: break
