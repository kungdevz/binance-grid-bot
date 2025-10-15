import asyncio
import json
import os
import pandas as pd
import websockets
from grid_bot.exchange import create_exchanges, ExchangeSync
from grid_bot.strategy import USDTGridStrategy
from grid_bot.config import CONFIG

async def main():

    mode = CONFIG['mode']
    symbol = CONFIG['symbol']

    bot = USDTGridStrategy(
        symbol=symbol,
        db_path=CONFIG['db_path'],
        atr_period=CONFIG['atr_period'],
        atr_mean_window=CONFIG['atr_mean_window'],
        ema_periods=CONFIG['ema_periods']
    )

    bot.set_exchanges(spot, futures, symbol=symbol)

    if mode == 'forward_test':
        print('✅ Bot initialized for backtest mode')
        file_path = CONFIG['ohlcv_file']
        if os.path.exists(file_path):
            raise ValueError('OHLCV_FILE must be set in env or config for backtest')
        bot.run_from_file(file_path)
    else:
        api_key = CONFIG['binance_api_key']
        api_secret = CONFIG['binance_api_secret']
        testnet = CONFIG.get('binance_testnet', False)
        spot, futures = create_exchanges(api_key, api_secret, testnet)
        bot.set_exchanges(spot, futures, symbol)

        # Warm-up
        limit = CONFIG.get('warmup_limit', 1000)
        interval = CONFIG.get('timeframe', '1h')
        df_hist = spot.fetch_ohlcv(symbol, interval, limit=limit)
        df = pd.DataFrame(df_hist, columns=['Time','Open','High','Low','Close','Volume'])
        df['Time'] = pd.to_datetime(df['Time'], unit='ms')
        df.set_index('Time', inplace=True)
        bot.bootstrap(df)
        print('✅ Bot initialized for live mode')

    ws_symbol = CONFIG['ws_symbol'].replace("/", "").lower()
    uri = f"wss://stream.binance.com:9443/ws/{ws_symbol}@kline_{CONFIG['ws_timeframe']}"
    await connect_and_listen(uri, bot)

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
                        strat.on_candle(ts, o, h, l, c, v)
        except Exception as e:
            print(f"WebSocket error: {e}. Reconnecting in 5s…")
            await asyncio.sleep(5)

if __name__ == '__main__':
    asyncio.run(main())
