from datetime import datetime
import unittest
from grid_bot.strategy import Strategy as strategy
from grid_bot.database.grid_states import GridState
from grid_bot.database.ohlcv_data import OhlcvData

class TestFunctionDB(unittest.TestCase):
    
    def setUp(self):
        self.strategy = strategy(
            symbol='ETH/USDT',
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

if __name__ == '__main__':
    unittest.main()