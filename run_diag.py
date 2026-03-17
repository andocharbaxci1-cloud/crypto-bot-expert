import crypto_bot

def run_diagnostics():
    print("--- Running Post-Fix Diagnostics ---")
    
    # 1. Test BTC Global Trend
    trend = crypto_bot.get_btc_global_trend()
    print(f"Detected Global BTC Trend: {trend}")
    
    # 2. Test check_signals directly using manual mode
    print("\nSimulating /analyze DOGE (1h):")
    # Using chat_id None so it doesn't actually send telegram message if we intercept it, 
    # but actually check_signals sends message if chat_id is provided. 
    # Let's mock send_message to just print to console to avoid spamming the user.
    original_send_message = crypto_bot.send_message
    
    def mock_send(chat_id, text):
        print(f"[Telegram Mock] {text}")
        
    crypto_bot.send_message = mock_send
    
    try:
        crypto_bot.check_signals('DOGE/USDT', '1h', btc_trend=trend, is_manual=True, chat_id="mock_chat")
    finally:
        crypto_bot.send_message = original_send_message

import sys
sys.stdout.reconfigure(encoding='utf-8')

if __name__ == "__main__":
    run_diagnostics()
