import math
import unittest
import pandas as pd
import numpy as np

from grid_bot.database.logger import Logger
from grid_bot.strategy import Strategy as strategy
from grid_bot.database.grid_states import GridState as GridState

class TestSpacingSize(unittest.TestCase):

    def setUp(self):
        self.strategy = strategy(
            symbol='BTC/USDT',
            atr_period=14,
            atr_mean_window=100,
            ema_periods=[9, 21, 50]
        )
        self.define_spacing_size = strategy.define_spacing_size

    def tearDown(self):
        self.strategy.acc_balance_db.delete_all_balances()
        return super().tearDown()
    
    def _mk_df(self, rows):
        """
        rows: list of (High, Low, Close)
        returns a DataFrame with columns High, Low, Close
        """
        return pd.DataFrame(rows, columns=["High", "Low", "Close"])

    def test_spacing_size_normal_case(self):
        atr_period = 5
        self.df = pd.DataFrame({
            'High': [10, 12, 11, 13, 15, 14],
            'Low': [8, 9, 10, 11, 12, 13],
            'Close': [9, 11, 10, 12, 14, 13]
        })
        spacing = self.strategy.define_spacing_size(atr_period, self.df)
        print(f"Calculated spacing: {spacing}")
        # test spacing numeric and positive
        self.assertTrue(spacing > 0)
        self.assertIsInstance(spacing, (int, float))

    def test_multiplier_is_2_when_last_TR_greater_than_ATR(self):
        """
        Construct data so that the last TR is strictly greater than the rolling ATR.
        We use atr_period=3 and craft the last candle to spike the TR.
        """
        # Rows: (High, Low, Close)
        # We’ll make the last bar volatile to ensure TR spikes above ATR.
        df = self._mk_df([
            (101,  99, 100),  # TR ~ 2
            (104, 101, 102),  # TR ~ max(3, |104-100|=4, |101-100|=1) = 4
            (103, 100, 101),  # TR ~ max(3, |103-102|=1, |100-102|=2) = 3
            (110, 104, 105),  # TR ~ max(6, |110-101|=9, |104-101|=3) = 9  (big spike)
        ])
        strat = self.strategy
        spacing = strat.define_spacing_size(atr_period=3, history=df)

        # Manually compute last TR and ATR(3)
        # Compute TR vector like the function
        tr = pd.concat([
            df['High'] - df['Low'],
            (df['High'] - df['Close'].shift()).abs(),
            (df['Low']  - df['Close'].shift()).abs()
        ], axis=1).max(axis=1)
        atr3 = tr.rolling(3).mean()

        last_tr = float(tr.iloc[-1])
        last_atr = float(atr3.iloc[-1])

        self.assertTrue(last_tr > last_atr, "Precondition failed: last TR should be > ATR")
        self.assertAlmostEqual(spacing, last_tr * 2.0, places=10)
        self.assertEqual(strat.prev_close, df['Close'].iloc[-1])

    def test_multiplier_is_1_when_last_TR_not_greater_than_ATR(self):
        """
        Build a steady series so TR is roughly equal/below ATR on the last bar.
        """
        df = self._mk_df([
            (101,  99, 100),  # TR ~ 2
            (102, 100, 101),  # TR ~ max(2, |102-100|=2, |100-100|=0) = 2
            (103, 101, 102),  # TR ~ max(2, |103-101|=2, |101-101|=0) = 2
            (104, 102, 103),  # TR ~ max(2, |104-102|=2, |102-102|=0) = 2
        ])
        strat = self.strategy
        spacing = strat.define_spacing_size(atr_period=3, history=df)

        tr = pd.concat([
            df['High'] - df['Low'],
            (df['High'] - df['Close'].shift()).abs(),
            (df['Low']  - df['Close'].shift()).abs()
        ], axis=1).max(axis=1)
        atr3 = tr.rolling(3).mean()

        last_tr = float(tr.iloc[-1])
        last_atr = float(atr3.iloc[-1])

        self.assertFalse(last_tr > last_atr, "Precondition failed: last TR should be <= ATR")
        self.assertAlmostEqual(spacing, last_tr * 1.0, places=10)
        self.assertEqual(strat.prev_close, df['Close'].iloc[-1])

    def test_handles_insufficient_rows_ATR_nan(self):
        """
        If there are fewer rows than atr_period, ATR on the last row is NaN.
        The comparison (TR > NaN) is False, so multiplier == 1.0 is expected.
        """
        df = self._mk_df([
            (101, 99, 100),  # TR ~ 2
            (102, 98,  99),  # TR ~ max(4, |102-100|=2, |98-100|=2) = 4
        ])
        strat = self.strategy
        spacing = strat.define_spacing_size(atr_period=5, history=df)

        tr = pd.concat([
            df['High'] - df['Low'],
            (df['High'] - df['Close'].shift()).abs(),
            (df['Low']  - df['Close'].shift()).abs()
        ], axis=1).max(axis=1)

        last_tr = float(tr.iloc[-1])
        # ATR is NaN when period > number of rows
        # In the function logic, (last_tr > NaN) -> False, so multiplier=1
        self.assertTrue(math.isnan(tr.rolling(5).mean().iloc[-1]))
        self.assertAlmostEqual(spacing, last_tr * 1.0, places=10)
        self.assertEqual(strat.prev_close, df['Close'].iloc[-1])


if __name__ == '__main__':
    unittest.main()