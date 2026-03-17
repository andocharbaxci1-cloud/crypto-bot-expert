import crypto_bot
import sys
sys.stdout.reconfigure(encoding='utf-8')

def run_scalp_diagnostics():
    print("--- Running Scalping Diagnostics ---")
    
    # Let's check DOGE/USDT on 5m
    symbol = 'DOGE/USDT'
    tf = '5m'
    
    print(f"\nSimulating /scalp {symbol} ({tf}):")
    # Using chat_id None won't send, but manual=True will print to console if no chat_id is provided, wait, check logic.
    # Ah, in check_scalping_signals, if chat_id is provided, it uses it, otherwise TELEGRAM_CHAT_IDS[0].
    # So we MUST mock send_message.
    original_send = crypto_bot.send_message
    
    def mock_send(chat_id, text):
        print(f"[Telegram Mock] {text}")
        
    crypto_bot.send_message = mock_send
    
    try:
        crypto_bot.check_scalping_signals(symbol, tf, btc_trend="NEUTRAL", is_manual=True, chat_id="mock_chat")
    except Exception as e:
        print(f"Error checking scalps: {e}")
    finally:
        crypto_bot.send_message = original_send

if __name__ == "__main__":
    run_scalp_diagnostics()
