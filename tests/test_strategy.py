import unittest
import pandas as pd
from strategy import USDTGridStrategy

class TestUSDTGridStrategy(unittest.TestCase):

    def setUp(self):
        self.bot = USDTGridStrategy(initial_capital=1000, mode='forward_test', db_path=':memory:')
        self.bot.set_exchanges(None, None, 'BTC/USDT')


    def test_initialization_grid(self):
        self.bot.initialize_grid(
            base_price=0.1,
            levels=5,
            spacing=0.01,
        )
        self.assertEqual(len(self.bot.grid), 5)

    def tearDown(self):
        return super().tearDown()

if __name__ == '__main__':
    unittest.main()