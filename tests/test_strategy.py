import unittest
import pandas as pd
import numpy as np

from grid_bot.database.logger import Logger
from grid_bot.strategy import USDTGridStrategy as strategy
from grid_bot.database.grid_states import GridState as GridState

class TestUSDTGridStrategy(unittest.TestCase):

    def setUp(self):
        self.strategy = strategy(
            symbol='BTC/USDT',
            atr_period=14,
            atr_mean_window=100,
            ema_periods=[9, 21, 50]
        )
        self.define_spacing_size = strategy.define_spacing_size
        self.df = pd.DataFrame({
            'Time': pd.date_range(start='2023-01-01', periods=10, freq='H'),
            'Open': [100 + i for i in range(1000)],
            'High': [105 + i for i in range(1000)],
            'Low': [95 + i for i in range(1000)],
            'Close': [102 + i for i in range(1000)],
            'Volume': [10 + i for i in range(1000)]
        })

    def tearDown(self):
        self.strategy.acc_balance_db.delete_all_balances()
        return super().tearDown()

    def test_spacing_size_normal_case(self):
        atr_period = 5
        spacing = self.strategy.define_spacing_size(atr_period, self.df)

        # check that columns are added
        self.assertIn("TR", self.strategy.df.columns)
        self.assertIn("ATR", self.strategy.df.columns)

        # check ATR not null for last candle
        self.assertFalse(np.isnan(self.strategy.df["ATR"].iloc[-1]))

        # ensure prev_close is stored correctly
        self.assertAlmostEqual(self.strategy.prev_close, self.df["Close"].iloc[-1])

        # test spacing numeric and positive
        self.assertTrue(spacing > 0)

    def test_spacing_multiplier_condition(self):
        """Test spacing multiplier 2x when TR > ATR"""
        df = self.df.copy()
        # Force last candle TR > ATR
        df.loc[df.index[-1], "High"] = 200
        df.loc[df.index[-1], "Low"] = 100
        atr_period = 3

        spacing = self.strategy.define_spacing_size(atr_period, df)

        # compute TR and ATR manually
        last = self.strategy.df.iloc[-1]
        expected_spacing = last["TR"] * (2.0 if last["TR"] > last["ATR"] else 1.0)

        self.assertAlmostEqual(spacing, expected_spacing, places=6)

    # def test_run_bootrap(self):
    #     # Create a mock DataFrame with historical data
    #     # mock data for OHLCV 1000 candles and ramdom values
    #     data = {
    #         'Time': pd.date_range(start='2023-01-01', periods=1000, freq='H'),
    #         'Open': [100 + i for i in range(1000)],
    #         'High': [105 + i for i in range(1000)],
    #         'Low': [95 + i for i in range(1000)],
    #         'Close': [102 + i for i in range(1000)],
    #         'Volume': [10 + i for i in range(1000)]
    #     }
    #     df = pd.DataFrame(data)

    #     # Initialize the strategy
    #     strategy = USDTGridStrategy(
    #         symbol='BTC/USDT',
    #         atr_period=14,
    #         atr_mean_window=100,
    #         ema_periods=[9, 21, 50]
    #     )

    #     strategy.bootstrap(df)


if __name__ == '__main__':
    unittest.main()