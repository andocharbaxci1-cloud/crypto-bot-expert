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
COMMAND_EXECUTOR = ThreadPoolExecutor(max_workers=10) 
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
    'adjustForTimeDifference': True,
    'options': {
        'defaultType': 'future'
    },
    'urls': {
        'api': {
            'public': 'https://api1.binance.com/api/v3',
            'private': 'https://api1.binance.com/api/v3',
            'fapiPublic': 'https://fapi.binance.com/fapi/v1',
            'fapiPrivate': 'https://fapi.binance.com/fapi/v1',
        }
    }
})

def get_funding_rate(symbol):
    try:
        funding = exchange.fetch_funding_rate(symbol)
        return funding.get('fundingRate', 0)
    except: return 0

def check_manipulation(df):
    try:
        last = df.iloc[-2]
        body = abs(last['close'] - last['open'])
        u_wick = last['high'] - max(last['open'], last['close'])
        l_wick = min(last['open'], last['close']) - last['low']
        if (u_wick > body * 3) or (l_wick > body * 3):
            return True, "⚠️ Manipulation Alert"
        return False, ""
    except: return False, ""

SIGNAL_HISTORY = {} 
STATS_FILE = "bot_stats.json"
TRADES_FILE = "active_trades.json"

def load_json(fp, d):
    if os.path.exists(fp):
        try:
            with open(fp, 'r') as f: return json.load(f)
        except: return d
    return d

def save_json(fp, data):
    try:
        with open(fp, 'w') as f: json.dump(data, f, indent=4)
    except Exception as e: print(f"Error saving {fp}: {e}")

def load_stats(): return load_json(STATS_FILE, {"date": datetime.now().strftime('%Y-%m-%d'), "signals": []})
def save_stats(s): save_json(STATS_FILE, s)
def load_active_trades(): return load_json(TRADES_FILE, [])
def save_active_trades(t): save_json(TRADES_FILE, t)

def add_active_trade(symbol, entry, tp1, tp2, sl, side):
    trades = load_active_trades()
    trades.append({
        "symbol": symbol, "entry": entry, "tp1": tp1, "tp2": tp2, "sl": sl,
        "current_sl": sl, "side": side, "status": "ENTRY", "last_price": entry,
        "time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })
    save_active_trades(trades)

def record_signal(symbol, timeframe, side):
    stats = load_stats()
    today = datetime.now().strftime('%Y-%m-%d')
    if stats.get("date") != today: stats = {"date": today, "signals": []}
    stats["signals"].append({"time": datetime.now().strftime('%H:%M:%S'), "symbol": symbol, "timeframe": timeframe, "side": side})
    save_stats(stats)

def update_signal_history(symbol, timeframe, side):
    SIGNAL_HISTORY[(symbol, timeframe, side)] = time.time()

def generate_daily_report():
    stats = load_stats(); signals = stats.get("signals", [])
    if not signals: return "📊 *Daily Summary*\nNo signals today."
    total = len(signals); today = stats.get("date")
    sym_counts = {}
    for s in signals: sym_counts[s['symbol']] = sym_counts.get(s['symbol'], 0) + 1
    top = max(sym_counts, key=sym_counts.get)
    msg = f"📊 *Daily Summary ({today})*\nTotal signals: `{total}`\nTop: `{top}` ({sym_counts[top]})\n"
    tf_counts = {}
    for s in signals: tf_counts[s['timeframe']] = tf_counts.get(s['timeframe'], 0) + 1
    for tf, count in tf_counts.items(): msg += f"• {tf}: `{count}` signals\n"
    return msg

def send_daily_report(): broadcast(generate_daily_report())

def is_volume_significant(df, threshold=1.5, period=20):
    try:
        avg = df['volume'].iloc[-period-1:-1].mean()
        curr = df['volume'].iloc[-2]
        return curr >= (avg * threshold) if avg > 0 else True
    except: return True

def get_high_volume_node(df, lookback=100, bins=20):
    try:
        rdf = df.iloc[-lookback-2:-2].copy()
        if rdf.empty: return 0
        min_p, max_p = rdf['low'].min(), rdf['high'].max()
        if min_p == max_p: return min_p
        bsize = (max_p - min_p) / bins
        vp = {min_p + (i * bsize): 0 for i in range(bins)}
        for _, row in rdf.iterrows():
            avg = (row['high'] + row['low'] + row['close']) / 3
            closest = min(vp.keys(), key=lambda k: abs(k - avg))
            vp[closest] += row['volume']
        return max(vp, key=vp.get)
    except: return 0

def log(msg): print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

def send_message(chat_id, text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}, timeout=15)
    except Exception as e: log(f"Error sending msg: {e}")

def broadcast(text):
    for cid in TELEGRAM_CHAT_IDS:
        if cid: send_message(cid, text)

app = Flask(__name__)
@app.route('/')
def home(): return "Bot is alive!"
def run_keep_alive():
    p = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=p)

def get_fear_and_greed_index():
    try:
        r = requests.get('https://api.alternative.me/fng/?limit=1', timeout=10)
        if r.status_code == 200:
            d = r.json()['data'][0]; v = int(d['value']); s = ""
            if v <= 25: s = "🔴 Extreme Fear"
            elif v <= 45: s = "🟠 Fear"
            elif v <= 55: s = "🟡 Neutral"
            elif v <= 75: s = "🟢 Greed"
            else: s = "🔥 Extreme Greed"
            return v, s
    except: pass
    return None, "Unknown"

def check_order_book_walls(symbol, current_price):
    try:
        ob = exchange.fetch_order_book(symbol, limit=50)
        b, a = ob['bids'], ob['asks']
        mb = max(b, key=lambda x: x[1]) if b else [0, 0]
        ma = max(a, key=lambda x: x[1]) if a else [0, 0]
        msg = ""; sbv = sum(v for p, v in b); sav = sum(v for p, v in a)
        if mb[1] > (sbv * 0.2):
            msg += f"🐋 Wall (Buy): `{mb[0]}` (-{((current_price-mb[0])/current_price)*100:.2f}%)\n"
        if ma[1] > (sav * 0.2):
            msg += f"🐋 Wall (Sell): `{ma[0]}` (+{((ma[0]-current_price)/current_price)*100:.2f}%)\n"
        return msg if msg else "No large walls.\n"
    except: return ""

def monitor_active_trades():
    while True:
        try:
            trades = load_active_trades()
            if not trades: time.sleep(60); continue
            ut = []
            for t in trades:
                sym = t['symbol']; e = t['entry']; tp1 = t['tp1']; tp2 = t['tp2']; sl = t['sl']; side = t['side']; stat = t['status']; csl = t['current_sl']
                p = exchange.fetch_ticker(sym)['last']; rem = False; msg = ""
                if side == 'BUY':
                    if stat == "ENTRY" and p >= tp1: t['status'] = "TP1_HIT"; t['current_sl'] = e + (e*0.0005); msg = f"✅ {sym} TP1 Hit ({tp1:.4f})"
                    elif stat == "TP1_HIT" and p > t.get('last_high', e) * 1.01: t['last_high'] = p; ns = p * 0.99; t['current_sl'] = max(csl, ns); msg = f"🔥 {sym} Trailing SL: {t['current_sl']:.4f}"
                    if p >= tp2: msg = f"💰 {sym} TP2 Hit ({tp2:.4f})"; rem = True
                    elif p <= t['current_sl']: msg = f"🛑 {sym} SL Hit ({t['current_sl']:.4f})"; rem = True
                else: 
                    if stat == "ENTRY" and p <= tp1: t['status'] = "TP1_HIT"; t['current_sl'] = e - (e*0.0005); msg = f"✅ {sym} TP1 Hit ({tp1:.4f})"
                    elif stat == "TP1_HIT" and p < t.get('last_low', e) * 0.99: t['last_low'] = p; ns = p * 1.01; t['current_sl'] = min(csl, ns); msg = f"🔥 {sym} Trailing SL: {t['current_sl']:.4f}"
                    if p <= tp2: msg = f"💰 {sym} TP2 Hit ({tp2:.4f})"; rem = True
                    elif p >= t['current_sl']: msg = f"🛑 {sym} SL Hit ({t['current_sl']:.4f})"; rem = True
                if msg: broadcast(msg)
                if not rem: ut.append(t)
            save_active_trades(ut); time.sleep(120)
        except: time.sleep(30)

def get_data(symbol, tf, limit=300):
    b = exchange.fetch_ohlcv(symbol, tf, limit=limit)
    df = pd.DataFrame(b, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

def get_btc_global_trend():
    try:
        d4h = get_data('BTC/USDT', '4h', limit=250); d4h.ta.ema(length=200, append=True); d4h.ta.ema(length=50, append=True)
        l4h = d4h.iloc[-2]; slow = "NEUTRAL"
        if l4h['close'] > l4h['EMA_200'] and l4h['EMA_50'] > l4h['EMA_200']: slow = "UPTREND"
        elif l4h['close'] < l4h['EMA_200'] and l4h['EMA_50'] < l4h['EMA_200']: slow = "DOWNTREND"
        d1h = get_data('BTC/USDT', '1h', limit=100); d1h.ta.ema(length=50, append=True); d1h.ta.ema(length=20, append=True)
        l1h = d1h.iloc[-2]; fast = "NEUTRAL"
        if l1h['close'] > l1h['EMA_50'] and l1h['EMA_20'] > l1h['EMA_50']: fast = "UPTREND"
        elif l1h['close'] < l1h['EMA_50'] and l1h['EMA_20'] < l1h['EMA_50']: fast = "DOWNTREND"
        return "UPTREND" if fast == "UPTREND" else slow
    except: return "NEUTRAL"

def analyze_data(df):
    df.ta.macd(append=True); df.ta.rsi(length=14, append=True); df.ta.ema(length=50, append=True); df.ta.ema(length=200, append=True); df.ta.bbands(length=20, append=True); df.ta.atr(length=14, append=True)
    return df

def get_historical_winrate(df, mode='indicator'):
    bw, bt, sw, st = 0, 0, 0, 0; sidx = max(50, int(len(df)*0.1))
    for i in range(sidx, len(df)-50):
        if 'EMA_200' not in df.columns or pd.isna(df['EMA_200'].iloc[i]): continue
        c = df['close'].iloc[i]; e20 = df.get('EMA_20', df['EMA_50']).iloc[i]; e50 = df['EMA_50'].iloc[i]; e200 = df['EMA_200'].iloc[i]
        rs = df['RSI_14'].iloc[i]; mac = df['MACD_12_26_9'].iloc[i]; macs = df['MACDs_12_26_9'].iloc[i]; at = df['ATRr_14'].iloc[i]
        lb, ub = df['BBL_20_2.0_2.0'].iloc[i], df['BBU_20_2.0_2.0'].iloc[i]; low, high = df['low'].iloc[i], df['high'].iloc[i]; prs = df['RSI_14'].iloc[i-1]
        sb, ss = False, False
        if mode == 'indicator':
            if (e20 > e50 > e200) and (low <= e20*1.005) and (mac > macs) and (rs > prs): sb = True; tp, sl = c+(at*3), c-(at*1.5)
            elif (e20 < e50 < e200) and (high >= e20*0.995) and (mac < macs) and (rs < prs): ss = True; tp, sl = c-(at*3), c+(at*1.5)
        elif mode == 'scalp':
            if (low <= lb) and (rs > prs and rs < 45): sb = True; tp, sl = c*1.008, c*0.992
            elif (high >= ub) and (rs < prs and rs > 55): ss = True; tp, sl = c*0.992, c*1.008
        if sb:
            bt += 1
            for j in range(i+1, min(i+51, len(df))):
                if df['high'].iloc[j] >= tp: bw += 1; break
                elif df['low'].iloc[j] <= sl: break
        elif ss:
            st += 1
            for j in range(i+1, min(i+51, len(df))):
                if df['low'].iloc[j] <= tp: sw += 1; break
                elif df['high'].iloc[j] >= sl: break
    return (bw/(bt+0.001)*100), bt, (sw/(st+0.001)*100), st

def get_fibonacci_levels(df):
    rh, rl = df['high'].tail(100).max(), df['low'].tail(100).min()
    if pd.isna(rh) or pd.isna(rl): return 0, 0, 0, 0
    diff = rh - rl
    return rh, rl, rh - diff*0.382, rh - diff*0.618

def find_breakout_retest(df):
    try:
        res = df.iloc[-100:-5]['high'].max(); bout = False
        for i in range(-5, -1):
            if df.iloc[i]['close'] > res and df.iloc[i-1]['close'] < res: bout = True; break
        if bout:
            last = df.iloc[-2]; tol = res * 0.002
            if (last['low'] <= res+tol) and (last['close'] >= res-tol) and last['RSI_14'] < 65: return True, res, "Breakout & Re-Test"
        return False, 0, ""
    except: return False, 0, ""

def check_signals(symbol, timeframe, btc_trend="NEUTRAL", fng_data=None, is_manual=False, chat_id=None):
    if not is_manual:
        for s in ['BUY', 'SELL']:
            lt = SIGNAL_HISTORY.get((symbol, timeframe, s))
            if lt and (time.time() - lt < 4*3600): return
    try:
        df = get_data(symbol, timeframe, limit=1000); df = analyze_data(df); df.ta.ema(length=20, append=True)
        last, prev = df.iloc[-2], df.iloc[-3]; close, e20, e50, e200 = last['close'], last['EMA_20'], last['EMA_50'], last['EMA_200']
        rsi, mac, macs, atr = last['RSI_14'], last['MACD_12_26_9'], last['MACDs_12_26_9'], last['ATRr_14']
        sig, side, stype = None, None, ""; gbt = btc_trend
        if (e20 > e50 > e200) and (last['low'] <= e20*1.005) and (mac > macs) and (rsi > prev['RSI_14']):
            if gbt == "DOWNTREND":
                if is_manual: send_message(chat_id, f"⚠️ {symbol} LONG blocked (BTC Downtrend)")
            else: sig = "BUY 🟢 (LONG Trend)"; side = "BUY"; stype = f"Pullback + {gbt}"; entry = close; sl, tp = entry-(atr*1.5), entry+(atr*3.0)
        elif (e20 < e50 < e200) and (last['high'] >= e20*0.995) and (mac < macs) and (rsi < prev['RSI_14']):
            if gbt == "UPTREND":
                if is_manual: send_message(chat_id, f"⚠️ {symbol} SHORT blocked (BTC Uptrend)")
            else: sig = "SELL 🔴 (SHORT Trend)"; side = "SELL"; stype = f"Pullback + {gbt}"; entry = close; sl, tp = entry+(atr*1.5), entry-(atr*3.0)
        if not sig:
            isbr, rlvl, rtyp = find_breakout_retest(df)
            if isbr and gbt != "DOWNTREND":
                sig = "BUY 🟢 (LONG)"; side = "BUY"; stype = f"Action ({rtyp}) + {gbt}"; entry, sl, tp = close, close-(atr*1.2), close+(atr*3.5)
        rh, rl, f382, f618 = get_fibonacci_levels(df); bwr, bt, swr, st = get_historical_winrate(df); fv, fs = fng_data if fng_data else (None, "Unknown"); walls = check_order_book_walls(symbol, close)
        if sig:
            wr = bwr if side == 'BUY' else swr
            if wr < 50.0:
                if is_manual: send_message(chat_id, f"⚠️ {symbol} low wr: {wr:.1f}%")
                return
            if not is_volume_significant(df):
                if is_manual: send_message(chat_id, f"⚠️ {symbol} low volume")
                return
            tp1, tp2 = (entry+(atr*1.2) if side=='BUY' else entry-(atr*1.2)), tp
            msg = f"🔔 *SIGNAL: {symbol}* ({timeframe})\n🔥 {sig}\n🧠 `{stype}`\n💵 Entry: `{entry:.4f}`\n🎯 TP1: `{tp1:.4f}`\n🎯 TP2: `{tp2:.4f}`\n🛑 SL: `{sl:.4f}`\n📈 WR: `{wr:.1f}%`\n" + walls
            broadcast(msg)
            if is_manual and chat_id not in TELEGRAM_CHAT_IDS: send_message(chat_id, msg)
            update_signal_history(symbol, timeframe, side); record_signal(symbol, timeframe, side); add_active_trade(symbol, entry, tp1, tp2, sl, side)
        elif is_manual:
            msg = f"📊 *Analysis: {symbol}* ({timeframe})\nNo clear entry.\n" + walls
            send_message(chat_id, msg)
    except Exception as e:
        log(f"Error {symbol}: {e}")
        if is_manual: send_message(chat_id, f"❌ Analysis Error: {e}")

def check_scalping_signals(symbol, timeframe, btc_trend="NEUTRAL", is_manual=False, chat_id=None):
    if not is_manual:
        for s in ['BUY', 'SELL']:
            lt = SIGNAL_HISTORY.get((symbol, timeframe, s))
            if lt and (time.time() - lt < 1800): return
    try:
        df = get_data(symbol, timeframe, limit=500); df = analyze_data(df); last, prev = df.iloc[-2], df.iloc[-3]
        close, ema50, rsi, lb, ub, atr = last['close'], last['EMA_50'], last['RSI_14'], last['BBL_20_2.0_2.0'], last['BBU_20_2.0_2.0'], last['ATRr_14']
        if (atr * 3) / close < 0.008:
            if is_manual: send_message(chat_id, f"📊 {symbol} low volatility")
            return
        sig, side = None, None
        if (last['low'] <= lb) and (rsi > prev['RSI_14'] and rsi < 45):
            if btc_trend != "DOWNTREND" and close >= ema50: sig, side, entry, sl, tp = "BUY 🟢 (SCALP)", "BUY", close, close*0.992, close*1.008
        elif (last['high'] >= ub) and (rsi < prev['RSI_14'] and rsi > 55):
            if btc_trend != "UPTREND" and close <= ema50: sig, side, entry, sl, tp = "SELL 🔴 (SCALP)", "SELL", close, close*1.008, close*0.992
        if sig:
            if not is_volume_significant(df): return
            bwr, bt, swr, st = get_historical_winrate(df, mode='scalp'); wr = bwr if side == 'BUY' else swr
            if wr < 50.0: return
            tp1, tp2 = (entry*1.004 if side=='BUY' else entry*0.996), tp
            msg = f"⚡ *SCALP: {symbol}* ({timeframe})\n🔥 {sig}\n💵 Entry: `{entry:.4f}`\n🎯 TP1: `{tp1:.4f}`\n🎯 TP2: `{tp2:.4f}`\n🛑 SL: `{sl:.4f}`\n📈 WR: `{wr:.1f}%`"
            broadcast(msg)
            if is_manual and chat_id not in TELEGRAM_CHAT_IDS: send_message(chat_id, msg)
            record_signal(symbol, timeframe, side)
        elif is_manual: send_message(chat_id, f"📊 Scalp {symbol}: No signal")
    except Exception as e:
        log(f"Scalp error {symbol}: {e}")
        if is_manual: send_message(chat_id, f"❌ Scalp Error: {e}")

def check_pump_dump():
    try:
        trend = get_btc_global_trend(); fv, fs = get_fear_and_greed_index()
        for sym in SYMBOLS:
            try:
                b = exchange.fetch_ohlcv(sym, '5m', limit=100); df = pd.DataFrame(b, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df.ta.rsi(length=14, append=True); last, prev = df.iloc[-2], df.iloc[-12:-2]
                avol, vol, op, cp, r = prev['volume'].mean()+0.001, last['volume'], last['open'], last['close'], last.get('RSI_14', 50)
                change = ((cp-op)/op)*100
                if vol > (avol*2.5) and abs(change) >= 1.5:
                    dir = "🚀 PUMP" if change > 0 else "🩸 DUMP"; broadcast(f"🚨 *{dir}: {sym}*\n📊 Change: `{change:.2f}%`\n💵 Price: `{cp:.4f}`\n🌊 RSI: `{r:.1f}`\n" + check_order_book_walls(sym, cp))
            except: pass
    except: pass

def handle_command(chat_id, text):
    try:
        if text == '/status':
            fv, fs = get_fear_and_greed_index(); upt = datetime.now() - BOT_START_TIME; d, s = upt.days, upt.seconds; h, m = s//3600, (s%3600)//60
            send_message(chat_id, f"✅ *Active*\n⏱ Uptime: `{d}d {h}h {m}m`\n📊 Assets: {len(SYMBOLS)}\n🧠 Market: {fv} - {fs}")
        elif text.startswith('/analyze'):
            s = text.split()[1].upper() if len(text.split())>1 else None
            if s:
                if 'USDT' not in s: s += '/USDT'
                send_message(chat_id, f"⏳ Analyzing {s}..."); check_signals(s, '1h', is_manual=True, chat_id=chat_id)
            else: send_message(chat_id, "Usage: /analyze SOL")
        elif text.startswith('/scalp'):
            s = text.split()[1].upper() if len(text.split())>1 else None
            if s:
                if 'USDT' not in s: s += '/USDT'
                send_message(chat_id, f"⚡ Scalping {s}..."); check_scalping_signals(s, '15m', is_manual=True, chat_id=chat_id)
            else: send_message(chat_id, "Usage: /scalp SOL")
    except Exception as e: log(f"Cmd error: {e}")

def poll_telegram():
    luid = 0; log("Polling...")
    while True:
        try:
            r = requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?timeout=10&offset={luid}", timeout=20).json()
            if r.get('ok'):
                for u in r['result']:
                    luid = u['update_id']+1
                    if 'message' in u and 'text' in u['message']:
                        cid = str(u['message']['chat']['id'])
                        if cid in TELEGRAM_CHAT_IDS: COMMAND_EXECUTOR.submit(handle_command, cid, u['message']['text'])
        except Exception as e: log(f"Poll error: {e}"); time.sleep(10)

if __name__ == "__main__":
    os.system('cls' if os.name == 'nt' else 'clear'); log("Starting...")
    threading.Thread(target=run_keep_alive, daemon=True).start(); threading.Thread(target=poll_telegram, daemon=True).start(); threading.Thread(target=monitor_active_trades, daemon=True).start()
    broadcast("🤖 *CryptoBot EXPERT Online*\n/status, /analyze SOL, /scalp SOL")
    la, lp, ls, lr = 0, 0, 0, time.time()
    while True:
        try:
            cur = time.time()
            if cur-lp >= 300: check_pump_dump(); lp = cur
            if cur-ls >= 300:
                for tf in SCALPING_TIMEFRAMES:
                    with ThreadPoolExecutor(max_workers=5) as ex: [ex.submit(check_scalping_signals, s, tf) for s in SYMBOLS]
                ls = cur
            if cur-la >= 900:
                tr = get_btc_global_trend(); fng = get_fear_and_greed_index()
                for tf in TIMEFRAMES:
                    with ThreadPoolExecutor(max_workers=5) as ex: [ex.submit(check_signals, s, tf, tr, fng) for s in SYMBOLS]
                la = cur
            if cur-lr >= 86400: send_daily_report(); lr = cur
            time.sleep(10)
        except KeyboardInterrupt: break
