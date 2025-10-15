import unittest
from unittest.mock import MagicMock
from strategy import USDTGridStrategy

class TestUSDTGridStrategy(unittest.TestCase):
    def setUp(self):
        self.mock_db = MagicMock()

    def test_run_bootrap(self):
        # Create a mock DataFrame with historical data
        # mock data for OHLCV 1000 candles and ramdom values
        data = {
            'Time': pd.date_range(start='2023-01-01', periods=1000, freq='H'),
            'Open': [100 + i for i in range(1000)],
            'High': [105 + i for i in range(1000)],
            'Low': [95 + i for i in range(1000)],
            'Close': [102 + i for i in range(1000)],
            'Volume': [10 + i for i in range(1000)]
        }
        df = pd.DataFrame(data)

        # Initialize the strategy
        strategy = USDTGridStrategy(
            symbol='BTC/USDT',
            atr_period=14,
            atr_mean_window=100,
            ema_periods=[9, 21, 50]
        )

        strategy.bootstrap(df)
        

if __name__ == '__main__':
    unittest.main()