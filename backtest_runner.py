import os
import sys
import pandas as pd
from strategy import USDTGridStrategy
from logger import Logger
from config import CONFIG

def backtest_from_file(
        file_path: str,
        initial_capital: float,
        reserve_ratio: float,
        order_size_usdt: float,
        hedge_size_ratio: float,
        db_path: str,
        atr_period: int = 14,
        atr_mean_window: int = 100,
        logger: Logger = None,
    ):

    df = pd.read_csv(file_path, parse_dates=['Time'])
    df.rename(columns={'Time': 'Time', 'Open': 'Open', 'High': 'High',
                       'Low': 'Low', 'Close': 'Close', 'Volume': 'Volume'}, inplace=True)
    df.set_index('Time', inplace=True)

    bot = USDTGridStrategy(
        initial_capital=initial_capital,
        mode='forward_test',
        db_path=db_path,
        reserve_ratio=reserve_ratio,
        order_size_usdt=order_size_usdt,
        hedge_size_ratio=hedge_size_ratio,
        atr_period=atr_period,
        atr_mean_window=atr_mean_window,
        enivronment='development',
    )

    bot.set_exchanges(None, None, symbol=None)

    warmup_len = atr_mean_window
    history = df.iloc[:warmup_len]
    bot.bootstrap(history)

    for _, row in df.iloc[warmup_len:].iterrows():
        bot.on_candle(
            open=row['Open'],
            high=row['High'],
            low=row['Low'],
            close=row['Close'],
            volumn=row['Volume']
        )

    summary = bot.get_summary()
    logger.log(f"===== Backtest Summary =====", level="INFO")
    for k, v in summary.items():
        logger.log(f"{k}: {v}", level="INFO")

def main():
    initial_capital  = 10000
    reserve_ratio    = 0.3
    order_size_usdt  = 500
    hedge_size_ratio = 0.3
    db_path          = "./db/backtest_bot.db"
    atr_period       = 14
    atr_mean_window  = 100

    logger = Logger(env=CONFIG['environment'], db_path=db_path)
    file_path = "backtests/data/bnbusdt_1h.csv"

    if not file_path:
        logger.log(f"Environment variable OHLCV_FILE is required. in {sys.stderr} mode", level="ERROR")
        sys.exit(1)

    backtest_from_file(
        file_path=file_path,
        initial_capital=initial_capital,
        reserve_ratio=reserve_ratio,
        order_size_usdt=order_size_usdt,
        hedge_size_ratio=hedge_size_ratio,
        db_path=db_path,
        atr_period=atr_period,
        atr_mean_window=atr_mean_window,
        logger=logger
    )

if __name__ == '__main__':
    main()
