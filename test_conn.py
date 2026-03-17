import requests
import ccxt
import os

TELEGRAM_BOT_TOKEN = "8766650445:AAHC_xWUlHfD4qJHg3xwpGu1h60zyX_5d6w"

def check_binance():
    print("Checking Binance connectivity...")
    try:
        ex = ccxt.binance({'timeout': 10000})
        status = ex.fetch_status()
        print(f"Binance Status: {status['status']}")
        return True
    except Exception as e:
        print(f"Binance Error: {e}")
        return False

def check_telegram():
    print("Checking Telegram connectivity...")
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            print(f"Telegram Bot Name: {r.json()['result']['first_name']}")
            return True
        else:
            print(f"Telegram HTTP Error: {r.status_code}")
            return False
    except Exception as e:
        print(f"Telegram Error: {e}")
        return False

if __name__ == "__main__":
    b = check_binance()
    t = check_telegram()
    if b and t:
        print("\nSUCCESS: All APIs reachable.")
    else:
        print("\nFAILURE: One or more APIs unreachable.")
