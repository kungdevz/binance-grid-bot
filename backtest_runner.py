import os
import sys
import pandas as pd
from strategy import USDTGridStrategy
from config import CONFIG

def backtest_from_file(
    file_path: str,
    initial_capital: float,
    reserve_ratio: float,
    order_size_usdt: float,
    hedge_size_ratio: float,
    db_path: str,
    atr_period: int = 14,
    atr_mean_window: int = 100
):
    # 1. อ่านไฟล์ OHLCV
    df = pd.read_csv(file_path, parse_dates=['Time'])
    df.rename(columns={'Time': 'time', 'Open': 'open', 'High': 'high',
                       'Low': 'low', 'Close': 'close', 'Volume': 'volume'}, inplace=True)
    df.set_index('time', inplace=True)

    # 2. สร้าง bot ในโหมด forward_test
    bot = USDTGridStrategy(
        initial_capital=initial_capital,
        mode='forward_test',
        db_path=db_path,
        reserve_ratio=reserve_ratio,
        order_size_usdt=order_size_usdt,
        hedge_size_ratio=hedge_size_ratio,
        atr_period=atr_period,
        atr_mean_window=atr_mean_window,
        enivronment='development',  # ใช้โหมด development สำหรับ backtest
    )
    # ไม่ต้องเชื่อมต่อ exchange จริง
    bot.set_exchanges(None, None, symbol=None)

    # 3. Bootstrap เพื่อคำนวณ ATR และวางกริดแรก
    warmup_len = atr_mean_window
    history = df.iloc[:warmup_len]
    bot.bootstrap(history)

    # 4. วนอ่านแท่งเทียนที่เหลือทีละแท่ง
    for timestamp, row in df.iloc[warmup_len:].iterrows():
        bot.on_candle(
            open=row['open'],
            high=row['high'],
            low=row['low'],
            close=row['close'],
            volumn=row['volume']
        )

    # 5. แสดงสรุปผล
    summary = bot.get_summary()
    print("\n===== Backtest Summary =====")
    for k, v in summary.items():
        print(f"{k}: {v}")


def main():
    # อ่านค่า environment variables
    file_path       = os.getenv('OHLCV_FILE')
    if not file_path:
        print('Environment variable OHLCV_FILE is required.', file=sys.stderr)
        sys.exit(1)

    initial_capital  = 10000
    reserve_ratio    = 0.3
    order_size_usdt  = 500
    hedge_size_ratio = float(os.getenv('HEDGE_SIZE_RATIO', '0.5'))
    db_path          = os.getenv('DB_PATH', ':memory:')
    atr_period       = int(os.getenv('ATR_PERIOD', '14'))
    atr_mean_window  = int(os.getenv('ATR_MEAN_WINDOW', '100'))

    backtest_from_file(
        file_path=file_path,
        initial_capital=initial_capital,
        reserve_ratio=reserve_ratio,
        order_size_usdt=order_size_usdt,
        hedge_size_ratio=hedge_size_ratio,
        db_path=db_path,
        atr_period=atr_period,
        atr_mean_window=atr_mean_window
    )

if __name__ == '__main__':
    main()
