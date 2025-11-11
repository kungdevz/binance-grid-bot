import unittest
from unittest.mock import MagicMock
from grid_bot.exchange import ExchangeSync

class TestExchangeSync(unittest.TestCase):
    
    def setUp(self):
        self.exchange_sync = ExchangeSync("BTC/USDT", "BTCUSDT", "")

    def test_sync_grid_state_marks_only_buy_orders(self):
        pass

if __name__ == '__main__':
    unittest.main()