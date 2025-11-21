import asyncio
import json
import os
import pandas as pd
import websockets
from grid_bot.backtest_strategy import BacktestGridStrategy
from grid_bot.live_strategy import LiveGridStrategy
from grid_bot.database.logger import Logger

async def main():

    logger = Logger()
    mode = os.getenv('MODE')
    spot_symbol = os.getenv('SYMBOL')
    futures_symbol = os.getenv('FUTURES_SYMBOL') 

    # bot = Strategy(
    #     symbol=spot_symbol,
    #     futures_symbol=futures_symbol,
    #     atr_period=int(os.getenv('ATR_PERIOD')),
    #     atr_mean_window=int(os.getenv('ATR_MEAN_WINDOW')),
    #     mode=mode
    # )

    if mode == 'backtest':
        bt = BacktestGridStrategy(
            symbol=spot_symbol,
            symbol_future=futures_symbol,
            initial_capital=1000,
            grid_levels=5,
            atr_multiplier=1.0,
            order_size_usdt=140,
            reserve_ratio=0.3,
            logger=logger,
        )
        file_path = os.getenv('OHLCV_FILE')
        if not file_path or not os.path.exists(file_path):
            raise ValueError('OHLCV_FILE must be set in env or config for backtest and point to an existing file')
        bt._run(file_path)
    else:
        print('✅ Bot initialized for live mode')
    
    # ws_symbol = os.getenv("WS_SYMBOL").replace("/", "").lower()
    # uri = f"wss://stream.binance.com:9443/ws/{ws_symbol}@kline_{os.getenv("ws_timeframe")}"
    # await connect_and_listen(uri, bot)

async def connect_and_listen(uri, strat):
    """
    Connect to the WS URI, listen for messages, 
    dispatch closed 1h candles to strat.on_candle().
    Reconnects automatically on drop.
    """
    while True:
        try:
            async with websockets.connect(uri) as ws:
                print(f"Connected to {uri}")
                async for message in ws:
                    data = json.loads(message)
                    k = data.get("k", {})
                    if k.get("x"): # candle is closed
                        ts = k["T"]            # close time (ms)
                        o, h, l, c = map(float, (k["o"], k["h"], k["l"], k["c"]))
                        v = float(k["v"])
                        row = strat.on_candle(ts, o, h, l, c, v)
                        strat._process_tick(row)
        except Exception as e:
            print(f"WebSocket error: {e}. Reconnecting in 5s…")
            await asyncio.sleep(5)

if __name__ == '__main__':
    asyncio.run(main())
