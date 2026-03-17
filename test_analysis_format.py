import os
import sys
from dotenv import load_dotenv

if sys.stdout.encoding != 'utf-8':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import crypto_bot

def test_manual_analysis():
    print(f"Testing manual analysis format...")
    # Chat ID-ն վերցնում ենք առաջինը ցուցակից
    cid = crypto_bot.TELEGRAM_CHAT_IDS[0] if crypto_bot.TELEGRAM_CHAT_IDS else None
    if not cid:
        print("Error: No Chat IDs found.")
        return
        
    print(f"Target Chat ID: {cid}")
    # Մանուալ անալիզ SOL-ի համար
    crypto_bot.check_signals('SOL/USDT', '1h', btc_trend="UPTREND", fng_data=(45, "Neutral"), is_manual=True, chat_id=cid)
    print("Success: Analysis command sent to Telegram.")

if __name__ == "__main__":
    test_manual_analysis()
