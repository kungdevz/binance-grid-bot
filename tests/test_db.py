from datetime import datetime
import unittest
from grid_bot.strategy import Strategy as strategy
from grid_bot.database.grid_states import GridState
from grid_bot.database.ohlcv_data import OhlcvData

class TestDB(unittest.TestCase):
    
    def setUp(self):
        self.strategy = strategy(
            symbol='None',
            atr_period=14,
            atr_mean_window=100,
            ema_periods=[9, 21, 50]
        )

    def tearDown(self):
        self.strategy.grid_db.delete_all_states()
        self.strategy.acc_balance_db.delete_all_balances()

    def test_save_and_load_state(self):
        items = {
                'grid_price': "10000.0",
                'use_status': 'Y',
                'groud_id': "test_grid_0-1111",
                'base_price': float(10000.0),
                'spacing': float(100.0),
                'date' : datetime.now().strftime('%Y-%m-%d'),
                'time' : datetime.now().strftime('%H:%M:%S'),
                'create_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        self.strategy.grid_db.save_state(items)
        state = self.strategy.grid_db.load_state_with_use_flgs("Y")
        self.assertEqual(state[0]["groud_id"] == "test_grid_0-1111", True)

    def test_save_and_load_ohlcv(self):
        ohlcv = {
            "symbol": "BTCUSDT",
            "timestamp": 1730035200000,
            "open_price": 65000.0,
            "high_price": 65500.0,
            "low_price": 64800.0,
            "close_price": 65200.0,
            "volume": 120.45,
            "tr": 700.0,
            "atr_14": 450.0,
            "atr_28": 470.0,
            "ema_14": 65100.0,
            "ema_28": 64950.0,
            "ema_50": 64800.0,
            "ema_100": 64500.0,
            "ema_200": 64000.0
        }

        self.strategy.ohlcv.insert_ohlcv_data(ohlcv)
        loaded_ohlcv = self.strategy.ohlcv.get_recent_ohlcv(symbol='BTCUSDT', limit=1)[0]
        self.assertEqual(loaded_ohlcv['close_price'], 65200.0)

        self.strategy.ohlcv.delete_ohlcv_data(symbol='BTCUSDT', timestamp=1730035200000)
        self.assertEqual(len(self.strategy.ohlcv.get_recent_ohlcv_by_timestamp(symbol='BTCUSDT', timestamp=1730035200000)), 0)

if __name__ == '__main__':
    unittest.main()