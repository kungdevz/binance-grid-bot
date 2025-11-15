import unittest
from grid_bot.exchange import ExchangeSync

class TestExchangeSync(unittest.TestCase):
    
    def setUp(self):
        self.exchange_sync = ExchangeSync(symbol_spot="BTC/USDT", symbol_future="BTCUSDT", mode="back_test")

    def test_fetch_markets(self):
        spot = self.exchange_sync.spot.fetch_markets()
        print(f"{spot} \n")
        self.assertIsInstance(spot, list)

    def test_create_buy_orders(self):
        order = self.exchange_sync.place_limit_buy(symbol="BTC/USDT", price=95000.0, qty=0.001, exchange=True)
        print(f"{order} \n")
        self.assertIn('id', order)

    def test_fetch_open_orders(self):
        orders = self.exchange_sync.fetch_open_orders()
        print(f"{orders} \n")
        self.assertIsInstance(orders, list)

    def test_guery_sub_account(self):
        sub_account = self.exchange_sync.query_sub_account()
        print(f"{sub_account} \n")
        self.assertIsInstance(sub_account, dict)

    def test_market_info(self):
        market = self.exchange_sync.get_market_info(symbol="XRPUSDT")
        print(market)
        self.assertIsInstance(market, dict)

    def test_get_market_precision(self):
        precision = self.exchange_sync.get_market_precision(symbol="XRPUSDT", name="price")
        print(precision)
        self.assertGreater(precision, 0)

if __name__ == '__main__':
    unittest.main()