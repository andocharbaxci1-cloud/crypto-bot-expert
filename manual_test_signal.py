import os
import sys
from dotenv import load_dotenv

# Սահմանել կոդավորումը UTF-8
if sys.stdout.encoding != 'utf-8':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import crypto_bot

def test_manual_broadcast():
    # crypto_bot-ը արդեն կանչում է load_dotenv()
    print(f"Testing broadcast...")
    print(f"Token (first 10): {crypto_bot.TELEGRAM_BOT_TOKEN[:10] if crypto_bot.TELEGRAM_BOT_TOKEN else 'NONE'}")
    print(f"Target Chat IDs: {crypto_bot.TELEGRAM_CHAT_IDS}")
    
    test_msg = "🚨 *TEST SIGNAL*\n\nՍա փորձնական ազդանշան է՝ ստուգելու համար, թե արդյոք բոտը ճիշտ է ուղարկում հաղորդագրությունները:\n\n✅ Կապը հաստատված է:"
    
    try:
        crypto_bot.broadcast(test_msg)
        print("Success: Broadcast function completed.")
    except Exception as e:
        print(f"Error in broadcast: {e}")

if __name__ == "__main__":
    test_manual_broadcast()
