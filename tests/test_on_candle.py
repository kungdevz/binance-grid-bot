import unittest

from tests.fakes import FakeStrategy


class TestOnCandle(unittest.TestCase):
    def test_on_candle_inserts_and_returns_row(self):
        strat = FakeStrategy()
        timestamp = 1622548800000  # ms
        open_price = 100.0
        high_price = 110.0
        low_price = 90.0
        close_price = 105.0
        volume = 1000.0

        row = strat.on_candle(timestamp, open_price, high_price, low_price, close_price, volume)
        self.assertIsInstance(row, dict)
        self.assertEqual(row.get("timestamp"), timestamp)
        self.assertEqual(float(row.get("close")), close_price)
