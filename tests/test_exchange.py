import unittest
from unittest.mock import MagicMock
from exchange import ExchangeSync

class TestExchangeSync(unittest.TestCase):
    def setUp(self):
        # สร้าง mock ของ spot.exchange
        self.mock_spot = MagicMock()
        # กำหนดให้ fetch_open_orders คืนค่า order list
        self.mock_spot.fetch_open_orders.return_value = [
            {'side': 'buy',  'status': 'open', 'price': 100},
            {'side': 'sell', 'status': 'open', 'price':  99},
        ]
        self.sync = ExchangeSync(self.mock_spot, 'BTC/USDT')

    def test_sync_grid_state_marks_only_buy_orders(self):
        grid = [100.0, 99.0, 98.0]
        state = self.sync.sync_grid_state(grid)
        # ควรตั้ง True เฉพาะที่ price=100.0
        expected = {
            100.0: True,
            99.0: False,   # แม้มี sell order แต่ sync logic มองแค่ buy
            98.0: False,   # ไม่เจอ order ที่ price นี้
        }
        self.assertEqual(state, expected)
        # ตรวจสอบว่า fetch_open_orders ถูกเรียกด้วย symbol ถูกต้อง
        self.mock_spot.fetch_open_orders.assert_called_once_with('BTC/USDT')

if __name__ == '__main__':
    unittest.main()