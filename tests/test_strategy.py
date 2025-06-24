import unittest
import pandas as pd
from strategy import USDTGridStrategy

class TestUSDTGridStrategy(unittest.TestCase):
    def test_buy_and_sell_cycle(self):
        # สร้าง DataFrame จำลองที่ราคาอยู่ใน grid และขึ้นกลับมา
        df = pd.DataFrame([
            {'Open': 10, 'High': 10, 'Low': 10, 'Close': 10},
            {'Open': 10, 'High': 12, 'Low': 9,  'Close': 12},
        ], index=pd.date_range('2025-01-01', periods=2))
        # เตรียม ATR เพื่อข้าม dropna
        df['ATR'] = 1
        df['ATR_mean'] = 1

        bot = USDTGridStrategy(initial_capital=1000, mode='forward_test', db_path=':memory:')
        bot.set_exchanges(None, None, 'BTC/USDT')
        bot.run(df)
        summary = bot.get_summary()
        # ควรมีกำไรจาก grid
        self.assertGreater(summary['Realized Grid Profit (USDT)'], 0)

if __name__ == '__main__':
    unittest.main()