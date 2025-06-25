import asyncio
import json
import pandas as pd
import websockets
from exchange import create_exchanges, ExchangeSync
from strategy import USDTGridStrategy
from config import CONFIG

def fetch_historical(spot, symbol, interval, limit=500):
    ohlcv = spot.fetch_ohlcv(symbol, interval, limit=limit)
    df = pd.DataFrame(ohlcv, columns=["Time", "Open", "High", "Low", "Close", "Volume"])
    df['Time'] = pd.to_datetime(df['Time'], unit='ms')
    df.set_index('Time', inplace=True)
    return df

async def kline_listener(bot):
    uri = f"wss://stream.binance.com:9443/ws/{CONFIG['ws_symbol']}@kline_{CONFIG['ws_timeframe']}"
    async with websockets.connect(uri) as ws:
        while True:
            msg = json.loads(await ws.recv())
            k = msg['k']
            if k['x']:
                bot.on_candle(float(k['o']), float(k['h']), float(k['l']), float(k['c']), float(k['v']))
                print(f"✅ open: {k['o']} high: {k['h']} low: {k['l']} close: {k['c']} volume: {k['v']}")

async def main():

    spot, futures = create_exchanges(
        CONFIG['binance_api_key'], CONFIG['binance_api_secret'], CONFIG['binance_testnet'],
    )

    capital = CONFIG['initial_capital']
    symbol = CONFIG['symbol']

    spot_fee = float(spot.fetch_trading_fee(symbol)['maker'])
    futures_fee = 0.004

    bot = USDTGridStrategy(
        initial_capital=capital,
        mode=CONFIG['environment'],
        db_path=CONFIG['db_path'],
        spot_fee=spot_fee,
        futures_fee=futures_fee,
        reserve_ratio=CONFIG['reserve_ratio'],
        order_size_usdt=CONFIG['order_size_usdt'],
        hedge_size_ratio=CONFIG['hedge_size_ratio'],
        enivronment=CONFIG['environment'],
    )
    bot.set_exchanges(spot, futures, symbol=symbol)

    # Warm-up historical data
    historical = fetch_historical(spot, CONFIG['symbol'], CONFIG['timeframe'], limit=1000)
    bot.bootstrap(historical)
    print("✅ Bot initialized. Starting live data...")

    # Start listener
    await kline_listener(bot)

if __name__ == '__main__':
    asyncio.run(main())
