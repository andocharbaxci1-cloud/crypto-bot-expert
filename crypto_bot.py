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
from dotenv import load_dotenv

# Բեռնել .env ֆայլը
load_dotenv()

# ================= ԳԼՈԲԱԼ ՓՈՓՈԽԱԿԱՆՆԵՐ =================
BOT_START_TIME = datetime.now()
COMMAND_EXECUTOR = ThreadPoolExecutor(max_workers=10)
LOG_BUFFER = []
# ================= ԿԱՐԳԱՎՈՐՈՒՄՆԵՐ =================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# Չատի ID-ները ստորակետով բաժանված տեքստից վերածում ենք լիստի
_ids = os.getenv("TELEGRAM_CHAT_IDS", "")
TELEGRAM_CHAT_IDS = [i.strip() for i in _ids.split(",") if i.strip()]

SYMBOLS = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT',
    'ADA/USDT', 'AVAX/USDT', 'DOGE/USDT', 'LINK/USDT', 'DOT/USDT',
    'POL/USDT', 'LTC/USDT', 'BCH/USDT', 'ATOM/USDT', 'UNI/USDT'
]
TIMEFRAMES = ['1h', '4h'] 
SCALPING_TIMEFRAMES = ['30m']

exchange = ccxt.binance({
    'enableRateLimit': True,
    'adjustForTimeDifference': True,
    'timeout': 30000,
    'options': {
        'defaultType': 'future'
    },
    'proxies': {
        'http': os.getenv('PROXY_URL'),
        'https': os.getenv('PROXY_URL'),
    } if os.getenv('PROXY_URL') else None,
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

def log(msg):
    t = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    m = f"[{t}] {msg}"
    print(m, flush=True)
    try:
        with open('bot.log', 'a', encoding='utf-8') as f:
            f.write(m + "\n")
            f.flush()
    except: pass

log("=== Bot Script Initialized ===")

def send_message(chat_id, text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}, timeout=15)
    except Exception as e: log(f"Error sending msg: {e}")

def send_action(chat_id, action="typing"):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendChatAction"
        requests.post(url, json={'chat_id': chat_id, 'action': action}, timeout=5)
    except: pass

def broadcast(text):
    for cid in TELEGRAM_CHAT_IDS:
        if cid: send_message(cid, text)

app = Flask(__name__)
@app.route('/')
def home(): return "Bot is alive!"

@app.route('/health')
def health(): return {"status": "ok", "uptime": str(datetime.now() - BOT_START_TIME)}

@app.route('/logs')
def view_logs():
    try:
        if os.path.exists('bot.log'):
            with open('bot.log', 'r') as f:
                lines = f.readlines()
                return "<pre>" + "".join(lines[-100:]) + "</pre>"
        else:
            return "bot.log file not found."
    except Exception as e:
        return f"Error reading logs: {e}"

@app.route('/test-msg')
def test_msg():
    broadcast("🔔 Test message from Render server.")
    return "Attempted to send broadcast."

@app.route('/debug-env')
def debug_env():
    token = os.getenv("TELEGRAM_BOT_TOKEN", "MISSING")
    ids = os.getenv("TELEGRAM_CHAT_IDS", "MISSING")
    purl = os.getenv("PROXY_URL", "NOT_SET")
    return {
        "token_len": len(token),
        "token_prefix": token[:5] if token != "MISSING" else "N/A",
        "chat_ids_len": len(ids),
        "chat_ids": ids if ids != "MISSING" else "N/A",
        "proxy_set": purl != "NOT_SET"
    }

@app.route('/check-token')
def check_token():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token: return {"ok": False, "error": "Token missing in env."}
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10).json()
        return r
    except Exception as e:
        return {"ok": False, "error": str(e)}
def run_keep_alive():
    # Use gunicorn in production, but keep this for local testing
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
    try:
        b = exchange.fetch_ohlcv(symbol, tf, limit=limit)
        df = pd.DataFrame(b, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        if "418" in str(e) or "IP banned" in str(e):
            log(f"⚠️ Binance IP Banned (418). Cooling down for 60s...")
            time.sleep(60)
        raise e

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
    bw, bt, sw, st = 0, 0, 0, 0
    # Optimize: start from the end and check fewer candles to avoid long hangs
    total_len = len(df)
    check_limit = 500 # Increased lookback for better stats
    sidx = max(50, total_len - check_limit)
    
    for i in range(sidx, total_len-20):
        if 'EMA_200' not in df.columns or pd.isna(df['EMA_200'].iloc[i]): continue
        c = df['close'].iloc[i]
        e20 = df.get('EMA_20', df['EMA_50']).iloc[i]
        e50 = df['EMA_50'].iloc[i]
        e200 = df['EMA_200'].iloc[i]
        rs = df['RSI_14'].iloc[i]
        mac = df['MACD_12_26_9'].iloc[i]
        macs = df['MACDs_12_26_9'].iloc[i]
        at = df['ATRr_14'].iloc[i]
        lb, ub = df['BBL_20_2.0_2.0'].iloc[i], df['BBU_20_2.0_2.0'].iloc[i]
        low, high = df['low'].iloc[i], df['high'].iloc[i]
        prs = df['RSI_14'].iloc[i-1]
        
        sb, ss = False, False
        if mode == 'indicator':
            if (e20 > e50 > e200) and (low <= e20*1.005) and (mac > macs) and (rs > prs): 
                sb = True; tp, sl = c+(at*3), c-(at*1.5)
            elif (e20 < e50 < e200) and (high >= e20*0.995) and (mac < macs) and (rs < prs): 
                ss = True; tp, sl = c-(at*3), c+(at*1.5)
        elif mode == 'scalp':
            if (low <= lb) and (rs > prs and rs < 45): 
                sb = True; tp, sl = c*1.008, c*0.992
            elif (high >= ub) and (rs < prs and rs > 55): 
                ss = True; tp, sl = c*0.992, c*1.008
                
        if sb:
            bt += 1
            for j in range(i+1, min(i+51, total_len)):
                if df['high'].iloc[j] >= tp: bw += 1; break
                elif df['low'].iloc[j] <= sl: break
        elif ss:
            st += 1
            for j in range(i+1, min(i+51, total_len)):
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
        if (e20 > e50) and (last['low'] <= e20*1.005) and (mac > macs) and (rsi > prev['RSI_14']):
            sig = "BUY 🟢 (Trend Pullback)"; side = "BUY"; stype = f"Pullback + {gbt}"; entry = close; sl, tp = entry-(atr*1.5), entry+(atr*3.0)
        elif (e20 < e50) and (last['high'] >= e20*0.995) and (mac < macs) and (rsi < prev['RSI_14']):
            sig = "SELL 🔴 (Trend Pullback)"; side = "SELL"; stype = f"Pullback + {gbt}"; entry = close; sl, tp = entry+(atr*1.5), entry-(atr*3.0)
        
        if not sig:
            isbr, rlvl, rtyp = find_breakout_retest(df)
            if isbr:
                sig = "ACTION ⚡ (Breakout)"; side = "BUY" if close > rlvl else "SELL"; stype = f"Breakout ({rtyp})"; entry, sl, tp = close, close-(atr*1.2), close+(atr*3.5)
        rh, rl, f382, f618 = get_fibonacci_levels(df); bwr, bt, swr, st = get_historical_winrate(df); fv, fs = fng_data if fng_data else (None, "Unknown"); walls = check_order_book_walls(symbol, close)
        wr = bwr if side == 'BUY' else swr
        valid_sig = sig and (wr >= 45.0) and is_volume_significant(df)
        
        if valid_sig:
            log(f"Signal Found: {symbol} {side} WR:{wr}%")
            entry = close
            sl, tp = (entry-(atr*1.5) if side=='BUY' else entry+(atr*1.5)), (entry+(atr*3.0) if side=='BUY' else entry-(atr*3.0))
            tp1, tp2 = (entry+(atr*1.2) if side=='BUY' else entry-(atr*1.2)), tp
            tr = btc_trend; fr = get_funding_rate(symbol); move_sl_rule = "🛡 ԿԱՆՈՆ: TP1-ին հասնելիս SL-ը տեղափոխիր Entry!"
            move_pct = abs(((tp2 - entry)/entry)*100)
            
            msg = (
                f"🎯 Սպասվող Շարժը: {move_pct:.1f}%+\n"
                f"🔥 Գործարք: {side} 🟢 ({'LONG' if side=='BUY' else 'SHORT'} TREND)\n"
                f"🌐 BTC Տրենդ: {tr}\n"
                f"💵 Մուտք (Entry): `{entry:.4f}`\n\n"
                f"✅ Take Profit 1: `{tp1:.4f}`\n"
                f"✅ Take Profit 2: `{tp2:.4f}`\n"
                f"🛑 Stop Loss: `{sl:.4f}`\n\n"
                f"{move_sl_rule}\n\n"
                f"📈 Win-Rate: `{wr:.1f}%` (հիմնված վերջին տվյալների վրա)\n"
                f"🌐 Funding: `{fr:.4f}%` ✅\n\n"
                f"🧠 Ինչու՞: {stype} ({timeframe} mode)։\n"
                f"{walls}"
            )
            broadcast(msg)
            if is_manual and chat_id not in TELEGRAM_CHAT_IDS: send_message(chat_id, msg)
            update_signal_history(symbol, timeframe, side); record_signal(symbol, timeframe, side); add_active_trade(symbol, entry, tp1, tp2, sl, side)
        elif is_manual:
            rh, rl, f382, f618 = get_fibonacci_levels(df)
            fv, fs = fng_data if fng_data else (None, "Անհայտ")
            tr = btc_trend
            trend_str = "Աճող 🟢" if last['EMA_20'] > last['EMA_50'] else "Նվազող 🔴"
            
            msg = (
                f"📊 Անալիզ: {symbol} ({timeframe}) ✅\n\n"
                f"Գործարքի հստակ ՄՈՒՏՔԱՅԻՆ ազդանշան չկա այս պահին։ Համբերեք...\n\n"
                f"📉 Ինդիկատորներ:\n"
                f"• Գինը Հիմա: {close:.4f}\n"
                f"• RSI: {rsi:.1f}\n"
                f"• Տրենդ: {trend_str}\n\n"
                f"📏 Դիմադրություն և Աջակցություն:\n"
                f"• Դիմադրություն (Max High): {rh:.4f}\n"
                f"• Ոսկե Fibo (0.618): {f618:.4f}\n"
                f"• Աջակցություն (Min Low): {rl:.4f}\n\n"
                f"🧠 Շուկայի հոգեբանություն: {fv if fv else 'None'}/100 - {fs}\n"
                f"🌐 BTC Գլոբալ Տրենդ (4h): {tr}\n\n"
                f"{walls if walls.strip() else 'No large walls.'}"
            )
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
        valid_sig = sig and is_volume_significant(df)
        
        if valid_sig:
            bwr, bt, swr, st = get_historical_winrate(df, mode='scalp'); wr = bwr if side == 'BUY' else swr
            if wr < 45.0:
                if is_manual: send_message(chat_id, f"📊 Scalp {symbol}: {wr:.1f}% Winrate is too low.")
                return
            log(f"Scalp Signal Found: {symbol} {side}")
            entry = close
            sl, tp = (entry-(atr*1.2) if side=='BUY' else entry+(atr*1.2)), (entry+(atr*2.5) if side=='BUY' else entry-(atr*2.5))
            tr = btc_trend; fr = get_funding_rate(symbol); move_sl_rule = "🛡 ԿԱՆՈՆ: 0.5% շահույթի դեպքում SL-ը տեղափոխիր Entry!"
            move_pct = abs(((tp - entry)/entry)*100)
            
            msg = (
                f"⚡ SCALPING: {side} 🟢 ({symbol})\n"
                f"🎯 Սպասվող Շարժը: {move_pct:.1f}%+\n\n"
                f"💵 Մուտք (Entry): `{entry:.4f}`\n"
                f"✅ Take Profit: `{tp:.4f}`\n"
                f"🛑 Stop Loss: `{sl:.4f}`\n\n"
                f"{move_sl_rule}\n\n"
                f"📈 Win-Rate: `{wr:.1f}%`\n"
                f"🧠 Ռեժիմ: {timeframe} Scalping\n"
                f"🌐 Funding: `{fr:.4f}%` ✅\n"
                f"🌐 BTC Տրենդ: {tr}\n"
            )
            broadcast(msg)
            if is_manual and chat_id not in TELEGRAM_CHAT_IDS: send_message(chat_id, msg)
            update_signal_history(symbol, timeframe, side); record_signal(symbol, timeframe, side)
        elif is_manual: 
            send_message(chat_id, f"📊 Scalp {symbol}: Հստակ ազդանշան չկա այս պահին։")
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
        text = text.lower().strip()
        if text == '/status' or text == 'status':
            send_action(chat_id, "typing")
            fv, fs = get_fear_and_greed_index()
            upt = datetime.now() - BOT_START_TIME
            d, s = upt.days, upt.seconds
            h, m = s//3600, (s%3600)//60
            send_message(chat_id, f"✅ *Bot is Active*\n⏱ Uptime: `{d}d {h}h {m}m`\n📊 Assets: {len(SYMBOLS)}\n🧠 Market: {fv} - {fs}")
            
        elif text.startswith('/analyze') or text.startswith('analyze'):
            parts = text.split()
            s = parts[1].upper() if len(parts) > 1 else None
            if s:
                if 'USDT' not in s: s += '/USDT'
                send_action(chat_id, "typing")
                send_message(chat_id, f"⏳ Analyzing {s}...")
                check_signals(s, '1h', is_manual=True, chat_id=chat_id)
            else:
                send_message(chat_id, "Usage: `/analyze SOL` or `analyze SOL`")
                
        elif text.startswith('/scalp') or text.startswith('scalp'):
            parts = text.split()
            s = parts[1].upper() if len(parts) > 1 else None
            if s:
                if 'USDT' not in s: s += '/USDT'
                send_action(chat_id, "typing")
                send_message(chat_id, f"⚡ Scalping {s}...")
                check_scalping_signals(s, '30m', is_manual=True, chat_id=chat_id)
            else:
                send_message(chat_id, "Usage: `/scalp SOL` or `scalp SOL`")
        
        else:
            # Optional: handle unknown commands if needed
            pass
            
    except Exception as e:
        log(f"Cmd error: {e}")
        send_message(chat_id, f"❌ Error processing command: {e}")

def poll_telegram():
    local_token = TELEGRAM_BOT_TOKEN
    local_ids = TELEGRAM_CHAT_IDS
    log(f"Thread: poll_telegram started. Token exists: {bool(local_token)}")
    luid = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{local_token}/getUpdates?timeout=10&offset={luid}"
            r = requests.get(url, timeout=20).json()
            if r.get('ok'):
                for u in r['result']:
                    luid = u['update_id']+1
                    if 'message' in u and 'text' in u['message']:
                        msg_obj = u['message']
                        cid = str(msg_obj['chat']['id'])
                        txt = msg_obj.get('text', "")
                        log(f"Received msg from {cid}: {txt[:10]}...")
                        if cid in local_ids:
                            handle_command(cid, txt)
                        else:
                            log(f"Ignored msg from unauthorized ID: {cid}")
            else:
                log(f"Poll fail (not ok): {r}")
                time.sleep(5)
        except Exception as e:
            log(f"Poll error: {e}")
            time.sleep(10)

def run_bot_logic():
    log("Bot logic thread started...")
    la, lp, ls, lr = 0, 0, 0, time.time()
    while True:
        try:
            cur = time.time()
            if cur-lp >= 600: check_pump_dump(); lp = cur # Increased from 300 to 600
            if cur-ls >= 600: # Increased from 300 to 600
                for tf in SCALPING_TIMEFRAMES:
                    with ThreadPoolExecutor(max_workers=5) as ex: [ex.submit(check_scalping_signals, s, tf) for s in SYMBOLS]
                ls = cur
            if cur-la >= 1200: # Increased from 900 to 1200
                tr = get_btc_global_trend(); fng = get_fear_and_greed_index()
                for tf in TIMEFRAMES:
                    with ThreadPoolExecutor(max_workers=5) as ex: [ex.submit(check_signals, s, tf, tr, fng) for s in SYMBOLS]
                la = cur
            if cur-lr >= 86400: send_daily_report(); lr = cur
            time.sleep(20) # Increased from 10 to 20
        except Exception as e:
            log(f"Main loop error: {e}")
            time.sleep(30)

def start_bot():
    try:
        log(f"Starting background threads... Chat IDs: {len(TELEGRAM_CHAT_IDS)}, Token prefix: {str(TELEGRAM_BOT_TOKEN)[:5]}")
        threading.Thread(target=poll_telegram, daemon=True).start()
        threading.Thread(target=monitor_active_trades, daemon=True).start()
        threading.Thread(target=run_bot_logic, daemon=True).start()
        log("All threads started. Attempting broadcast...")
        broadcast("🤖 *CryptoBot EXPERT Online*\n/status, /analyze SOL, /scalp SOL")
        log("Broadcast sent.")
    except Exception as e:
        log(f"Startup error: {e}")

# Միացնում ենք բոտը հենց մոդուլը բեռնվում է (Gunicorn-ի համար)
if not os.environ.get("WERKZEUG_RUN_MAIN"): # Խուսափել կրկնակի միացումից Flask debug mode-ում
    start_bot()

if __name__ == "__main__":
    os.system('cls' if os.name == 'nt' else 'clear'); log("Starting manually...")
    run_keep_alive()
