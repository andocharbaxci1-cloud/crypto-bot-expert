import pandas as pd
import sys
from unittest.mock import MagicMock

# Mock CCXT and other dependencies before importing crypto_bot
import pandas as pd
from unittest.mock import MagicMock

# Mock the 'ta' accessor on pandas DataFrame
class TAMock:
    def __init__(self, df):
        self.df = df
    def ema(self, **kwargs):
        pass
    def macd(self, **kwargs):
        pass

pd.DataFrame.ta = property(lambda self: TAMock(self))

sys_mock = MagicMock()
sys.modules['ccxt'] = sys_mock
sys.modules['pandas_ta'] = MagicMock()

import crypto_bot

def test_trend_logic():
    print("Testing get_btc_global_trend logic...")
    
    # Mock get_data
    crypto_bot.get_data = MagicMock()
    
    # CASE 1: 4h is DOWNTREND, but 1h is UPTREND (Rapid reversal)
    # 4h data (Downtrend: close < EMA200 and EMA50 < EMA200)
    df_4h_down = pd.DataFrame({
        'close': [60000, 59000],
        'EMA_50': [62000, 61000],
        'EMA_200': [65000, 65000]
    })
    # 1h data (Uptrend: close > EMA50 and EMA20 > EMA50)
    df_1h_up = pd.DataFrame({
        'close': [62000, 63000],
        'EMA_20': [61000, 62000],
        'EMA_50': [60000, 61000]
    })
    
    crypto_bot.get_data.side_effect = [df_4h_down, df_1h_up]
    
    trend = crypto_bot.get_btc_global_trend()
    print(f"Detected trend (Reversal Case): {trend}")
    assert trend == "NEUTRAL", f"Expected NEUTRAL, got {trend}"

    # CASE 2: Both are UPTREND (Uptrend: close > EMA200 and EMA50 > EMA200)
    df_4h_up = pd.DataFrame({
        'close': [67000, 68000],
        'EMA_50': [66000, 67000],
        'EMA_200': [65000, 65000]
    })
    df_1h_up_2 = pd.DataFrame({
        'close': [68000, 69000],
        'EMA_20': [67000, 68000],
        'EMA_50': [66000, 67000]
    })
    crypto_bot.get_data.side_effect = [df_4h_up, df_1h_up_2]
    trend = crypto_bot.get_btc_global_trend()
    print(f"Detected trend (Uptrend Case): {trend}")
    assert trend == "UPTREND", f"Expected UPTREND, got {trend}"

    print("Verification passed!")

if __name__ == "__main__":
    try:
        test_trend_logic()
    except Exception as e:
        print(f"❌ Verification failed: {e}")
