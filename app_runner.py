import asyncio
import json
import os
import pandas as pd
import websockets
from exchange import create_exchanges, ExchangeSync
from strategy import USDTGridStrategy
from config import CONFIG

def main():

    capital = CONFIG['initial_capital']
    symbol  = CONFIG['symbol']
    mode    = CONFIG['mode']

    spot, futures = create_exchanges(CONFIG['binance_api_key'], CONFIG['binance_api_secret'], CONFIG['binance_testnet'])

    if mode == 'live':
        spot_fee = float(spot.fetch_trading_fee(symbol)['maker'])
        futures_fee = 0.004
    else:
        spot_fee = 0.1
        futures_fee = 0.004

    bot = USDTGridStrategy(
        mode=mode,
        symbol=symbol,
        spot_fee=spot_fee,
        futures_fee=futures_fee,
        initial_capital=capital,
        reserve_ratio=CONFIG['reserve_ratio'],
        order_size_usdt=CONFIG['order_size_usdt'],
        hedge_size_ratio=CONFIG['hedge_size_ratio'],
        enivronment=CONFIG['environment'],
        atr_period=CONFIG['atr_period'],
        ema_periods=CONFIG['ema_periods']
    )

    bot.set_exchanges(spot, futures, symbol=symbol)

    if mode == 'forward_test':
        print('✅ Bot initialized for backtest mode')
        file_path = CONFIG.get('ohlcv_file') or os.getenv('OHLCV_FILE')
        if not file_path:
            raise ValueError('OHLCV_FILE must be set in env or config for backtest')
        summary = bot.run_from_file(file_path)
        print("===== Backtest Summary =====")
        for k, v in summary.items():
            print(f"{k}: {v}")
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

        async def live_loop():
            uri = f"wss://stream.binance.com:9443/ws/{CONFIG['ws_symbol']}@kline_{CONFIG['ws_timeframe']}"
            async with websockets.connect(uri) as ws:
                while True:
                    data = json.loads(await ws.recv())
                    k = data['k']
                    if k['x']:
                        bot.on_candle(
                            int(k['t']),
                            float(k['o']), float(k['h']), float(k['l']), float(k['c']), float(k['v'])
                        )
        asyncio.run(live_loop())

if __name__ == '__main__':
    main()
