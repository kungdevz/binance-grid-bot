import os
import pandas as pd
import numpy as np
from typing import Any, Dict, List, Tuple, Optional
from datetime import datetime, timedelta

from grid_bot.database.future_orders import FuturesOrders
from grid_bot.database.grid_states import GridState
from grid_bot.database.ohlcv_data import OhlcvData
from grid_bot.database.spot_orders import SpotOrders
from grid_bot.database.account_balance import AccountBalance

from grid_bot.exchange import ExchangeSync as exchange
from grid_bot.database.logger import Logger

import grid_bot.utils.util as util

class Strategy:

    def __init__(
        self,
        symbol: str,
        futures_symbol: str,
        atr_period: int = 14,
        atr_mean_window: int = 100,
        mode: str = "forward_test"
    ):
        # Basic configuration from .env
        self.symbol = symbol
        self.futures_symbol = futures_symbol
        self.atr_period = atr_period
        self.atr_mean_window = atr_mean_window
        self.ema_periods = {
            'ema_14': 14,
            'ema_28': 28,
            'ema_50': 50,
            'ema_100': 100,
            'ema_200': 200
        }

        # Mode and grid parameters
        self.reserve_ratio = float(os.getenv("RESERVE_RATIO", 0.3))  # Portion of capital reserved
        self.grid_levels = int(os.getenv("GRID_LEVELS", 5))
        
        # Initialize Logger
        self.logger = Logger()
        self.logger.log(f"Initializing strategy in {mode} mode", level="DEBUG", env=os.getenv("ENVIRONMENT", "development"))
        self.mode = mode

        # Initialize databases
        self.grid_db        = GridState()
        self.ohlcv_db       = OhlcvData()
        self.spot_db        = SpotOrders()
        self.futures_db     = FuturesOrders()
        self.acc_balance_db = AccountBalance()
        self.spot_order_db  = SpotOrders()

        if mode == "live":
            self._init_live_mode()
        elif self.mode == "forward_test":
            self._init_capital_and_fees()
            self._init_forward_mode()
        elif self.mode == "backtest":
            self._init_capital_and_fees()
            self._init_forward_mode()
        else:
            self._init_capital_and_fees()
            self._init_forward_mode()

        self.reset()

    """ Fees and initial capital will be loaded per mode, Initialize capital, exchanges, fees, balances, and positions """
    def _init_capital_and_fees(self):
        self.initial_capital = float(os.getenv("INITIAL_CAPITAL", 10000))
        self.spot_fee        = float(os.getenv("SPOT_FEE", 0.001))
        self.futures_fee     = float(os.getenv("FUTURES_FEE", 0.0004))
        self.reserve_capital = self.initial_capital * self.reserve_ratio

    def _init_live_mode(self):
        # Connect to exchanges
        api_key       = os.getenv("API_SPOT_KEY")
        api_secret    = os.getenv("API_SPOT_SECRET")
        spot, futures = exchange()
        self.set_exchanges(spot, futures, self.symbol, mode="live")

        # Fetch fees from exchange
        self.spot_fee    = self.spot.get_trade_fee()
        self.futures_fee = self.futures.get_trade_fee()

        # Sync account balance
        balance = self.spot.get_account_balance(asset="USDT")
        self.initial_capital = balance.total  # total USDT balance
        self.logger.log(f"Live USDT balance fetched: {self.initial_capital}", level="INFO")

        # Persist balance record
        self.acc_balance_db.insert_balance({
            "record_date": datetime.now().strftime("%Y-%m-%d"),
            "record_time": datetime.now().strftime("%H:%M:%S"),
            "start_balance_usdt":self.initial_capital,
            "end_balance_usdt": self.initial_capital,
            "notes": "Initial live balance"
        })

        # Sync open spot orders
        open_spots = self.spot.get_open_orders(self.symbol)
        for o in open_spots:
            self.spot_db.create_order(o)
        self.logger.log(f"Synchronized {len(open_spots)} live spot orders", level="INFO")

        # Sync open futures positions
        open_futs = self.futures.get_open_orders(self.symbol)
        for f in open_futs:
            self.futures_db.create_order(f)
        self.logger.log(f"Synchronized {len(open_futs)} live futures orders", level="INFO")

    def _init_forward_mode(self):
        # Forward-test: initial capital already set, record it
        self.logger.log(f"Forward-test capital: {self.initial_capital}", level="INFO")
        self.reserve_capital = self.initial_capital * self.reserve_ratio
        self.logger.log(f"Reserve capital set to {self.reserve_capital}", level="DEBUG")
        self.order_size_usdt = (self.initial_capital - self.reserve_capital) / self.grid_levels
        self.logger.log(f"Order size set to {self.order_size_usdt} USDT", level="DEBUG")
        self.set_exchanges(None, None, self.symbol, self.futures_symbol, mode=self.mode)
        self.acc_balance_db.insert_balance({
            "record_date": datetime.now().strftime("%Y-%m-%d"),
            "record_time": datetime.now().strftime("%H:%M:%S"),
            "start_balance_usdt":self.initial_capital,
            "end_balance_usdt": self.initial_capital,
            "notes" : "Initial forward-test balance"
        })

    def set_exchanges(self, spot: Any, futures: Any, spot_symbol: str, future_symbol: str, mode: str = "forward_test"):
        self.spot = spot
        self.futures = futures
        self.symbol = spot_symbol
        self.symbol_futures = future_symbol
        self.exchange_sync = exchange(spot, spot_symbol, mode)
        self.logger.log(f"Exchanges set for symbol spot: {spot_symbol}, future spot: {future_symbol}", level="DEBUG")

    def reset(self):
        self.available_capital = self.initial_capital * (1 - self.reserve_ratio)
        self.reserve_capital = self.initial_capital * self.reserve_ratio
        self.realized_grid_profit = 0.0
        self.realized_hedge_profit = 0.0
        self.grid_initialized = False
        self.hedge_active = False
        self.hedge_entry_price = 0.0
        self.hedge_qty = 0.0
        self.prev_close = None
        self.data_file_path = None
        self.logger.log("Strategy state reset", level="DEBUG")

    def run_from_file(self, file_path: str) -> Dict[str, Any]:
        """
        Read OHLCV CSV and execute backtest.
        CSV must have columns: Time, Open, High, Low, Close, Volume
        """
        df = pd.read_csv(file_path, parse_dates=['Time'])
        df.rename(columns={'Time':'time','Open':'Open','High':'High','Low':'Low','Close':'Close','Volume':'Volume'}, inplace=True)
        df.set_index('time', inplace=True)

        # Bootstrap and process each candle 
        self.bootstrap(history=df)
        for idx, row in df.iterrows():
            # convert pandas Timestamp to epoch ms
            ts = int(idx.value // 10**6)
            row = self.on_candle(self.symbol, ts, float(row['Open']), float(row['High']), float(row['Low']), float(row['Close']), float(row['Volume']))
            self._process_tick(self.symbol, row)
        return self.get_summary()

    def load_grid_state(self):
        if self.mode == "forward_test" and self.db:
            self.grid_state = self.grid_db.load_state_with_use_flgs("Y")
            self.logger.log("Loaded grid state from SQLite", level="DEBUG")
        elif self.mode == "live" and self.exchange_sync and self.grid_initialized:
            self.grid_state = self.exchange_sync.sync_grid_state(self.grid_prices)
            self.logger.log("Synced grid state from exchange", level="DEBUG")
        else:
            self.grid_state = {}
            self.logger.log("Initialized empty grid state", level="DEBUG")        

    def initialize_grid(self, symbol: str, base_price: float, spacing: float, levels: int = 10) -> Tuple[str, List[float]]:
        
        lower = [float(round(base_price - spacing * i, 2)) for i in range(1, levels+1)]
        upper = [float(round(base_price + spacing * i, 2)) for i in range(1, levels+1)]

        grid_prices = upper + lower
        group_id = util.generate_order_id('INIT')
        self.logger.log(f"Grid initialized with base price: {base_price}, spacing: {spacing}, groud_id: {group_id}, prices: {grid_prices}", level="INFO")
        for price in grid_prices:
            items = {
                'symbol': symbol,
                'grid_price': price,
                'use_status': 'Y',
                'group_id': group_id,
                'base_price': float(base_price),
                'spacing': float(spacing),
                'date' : datetime.now().strftime('%Y-%m-%d'),
                'time' : datetime.now().strftime('%H:%M:%S'),
                'create_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            self.grid_db.save_state(items)

        return (group_id, grid_prices)
    
    def define_spacing_size(self, atr_period: int, history: pd.DataFrame) -> float:
        df = history.copy().reset_index(drop=True)
        # 1. calculate true range series
        tr = pd.concat([
            df['High'] - df['Low'],
            (df['High'] - df['Close'].shift()).abs(),
            (df['Low']  - df['Close'].shift()).abs()
        ], axis=1).max(axis=1)

        atr = tr.rolling(atr_period, min_periods=1).mean()
        df['TR'], df['ATR'] = tr, atr
        
        # track prev_close for first streaming candle
        self.prev_close = df['Close'].iloc[-1]

        # use last row to init grid
        last = df.iloc[-1]
        spacing = last['TR'] * (2.0 if last['TR'] > last['ATR'] else 1.0)
        return spacing

    def bootstrap(self, history: pd.DataFrame):
        spacing = self.define_spacing_size(history=history, atr_period=self.atr_period)
        grid_id, grid_prices = self.initialize_grid(symbol=self.symbol, base_price=history['Close'].iloc[-1],  spacing=spacing,  levels=self.grid_levels)
        self.place_initial_orders(order_size_usdt=self.order_size_usdt, grid_prices=grid_prices, grid_id=grid_id, center_price=history['Close'].iloc[-1])

    def place_initial_orders(self, order_size_usdt : float, grid_prices : list[float], grid_id : str, center_price : float):
        resp = {}
        for price in grid_prices:
            qty = round(order_size_usdt / price, 6)
            if self.mode == "live" and self.exchange_sync:
                if price < center_price:
                    resp = self.exchange_sync.place_limit_buy(self.symbol, price, qty, True)
                    self.logger.log(f"Placed live limit buy for {qty}@{price}", level="INFO")
                else:
                    resp = self.exchange_sync.place_limit_sell(self.symbol, price, qty, True)
                    self.logger.log(f"Placed live limit sell for {qty}@{price}", level="INFO")
                self.grid_state[price] = 'open'
            elif self.mode == "forward_test" or "backtest":
                self.logger.log(f"Simulated open {price}", level="INFO")
                resp = self.exchange_sync.place_limit_buy(self.symbol, price, qty, False)
                self.logger.log(f"Simulated open sell {qty}@{price}", level="INFO")

        self.spot_db.create_order({'symbol': resp['symbol'], 'side': resp['side'], 'order_id': resp['order_id'], 'grid_id': grid_id,
                                   'type': resp['type'], 'price': resp['price'], 'avg_price': resp['price'], 'amount': resp['amount'], 
                                   'status': resp['status'], 'time': resp['timestamp'], 'update_time': resp['timestamp']})

    def on_candle(self, symbol: str ,timestamp: int, open: float, high: float, low: float, close: float, volume: float) -> pd.Series:
        
        # fetch previous close and EMA values
        prev_df = self.ohlcv_db.get_recent_ohlcv(symbol, 1)
        if not prev_df.empty:
            prev_close = prev_df['close'].iloc[-1]
            prev_emas = {name: prev_df[name].iloc[-1] for name in self.ema_periods}
        else:
            prev_close = close
            prev_emas = {name: None for name in self.ema_periods}

        # calculate TR and ATR
        tr = self._calc_tr_single(high, low, prev_close)
        hist = self.ohlcv_db.get_recent_ohlcv(symbol, self.atr_period)['tr'].tolist()
        tr_list = (hist + [tr])[-self.atr_period:]
        atr_value = float(np.mean(tr_list))
        atr_mean = float(np.mean(tr_list))

        # calcalate EMA values
        emas: Dict[str, float] = {}
        for name, period in self.ema_periods.items():
            alpha = 2 / (period + 1)
            prev = prev_emas.get(name)
            emas[name] = float(close if prev is None else alpha * close + (1 - alpha) * prev)

        self.ohlcv_db.insert_ohlcv_data(symbol, timestamp, open, high, low, close, volume, tr, atr_value, emas)

        return pd.Series({ 'timestamp': timestamp, 'close': close, 'atr': atr_value, 'atr_mean': atr_mean, **emas }, name=timestamp)

    """ You must first use the following formula to calculate the true range: TR = Max [(H-L),|H- Cp|,|L-Cp|] 
        where 
            H = Current Period High
            L = Current Period Low
            Cp = Previous Period Close
        so that True Range (TR) is the greatest of the following:
            (H-L)   = Current High less the current Low
            |H- Cp| = Current High less the previous Close (absolute value)
            |L-Cp|  = Current Low less the previous Close (absolute value)
    """
    def _calc_tr_single(self, high: float, low: float, prev_close: float) -> float:
        tr1 = high - low
        tr2 = abs(high - prev_close)
        tr3 = abs(low  - prev_close)
        tr  = max(tr1, tr2, tr3)
        return tr

    def _process_tick(self, symbol, row: pd.Series) -> None:
        
        price = row['close']
        atr = row['atr']
        atr_avg = row['atr_mean']
        multiplier = 2.0 if atr > atr_avg else 1.0
        spacing = atr * multiplier

        grid_prices = self.grid_db.load_state_with_use_flgs("Y")

        for gp in grid_prices:
            price = gp["grid_price"]
            if price <= grid_prices and self.available_capital >= self.order_size_usdt:
                self._buy_grid(row.name, gp, spacing)

        self._check_sell(row.name, price)
        self._hedge_logic(price, atr)

    def _buy_grid(self, timestamp, price: float, spacing: float) -> None:
        qty = round(self.order_size_usdt / price, 6)
        fee = self.order_size_usdt * self.spot_fee
        self.available_capital -= (self.order_size_usdt + fee)
        target = round(price + spacing, 2)
        self.positions.append((qty, price, target, spacing))
        self.grid_state[price] = True
        self.logger.log(f"Grid Buy Price={price}, Targe Price={target}, Qty={qty}, Fee={fee}", level="DEBUG")

        if self.exchange_sync and self.mode == "live":
            self.exchange_sync.place_limit_buy(self.symbol, price, qty)
            self.logger.log(f"Placed live limit buy for Grid Buy Price={price}, Targe Price={target}, Qty={qty}, Fee={fee}", level="INFO")

    def _check_sell(self, timestamp, price: float) -> None:
        new_positions = []
        for qty, entry, target, spacing in self.positions:
            if price >= target:
                notional = qty * price
                fee = notional * self.spot_fee
                pnl = notional - (qty * entry) - fee
                self.available_capital += notional - fee
                self.realized_grid_profit += pnl
                self.logger.log(f"Grid SELL Entry Price={entry}, Sell Price={price}, Qty={qty}, Notional={notional}, Fee={fee}, PnL={pnl}", level="DEBUG")
                self.grid_state[entry] = False

                if self.exchange_sync and self.mode == "live":
                    self.exchange_sync.place_market_order(self.symbol, 'sell', qty)
                    self.logger.log(f"Placed live market sell for Sell Price={price}, Qty={qty}, Notional={notional}, Fee={fee}, PnL={pnl}", level="INFO")

                if self.db:
                    self.db.mark_filled(entry)

            else:
                new_positions.append((qty, entry, target, spacing))
        self.positions = new_positions

    def _hedge_logic(self, price: float, atr: float) -> None:
        if not self.hedge_active and self.positions and price < min(self.grid_prices) - atr:
            self.hedge_qty = sum(q for q, *_ in self.positions) * self.hedge_size_ratio
            self.hedge_entry_price = price
            if self.exchange_sync and self.mode == "live":
                self.exchange_sync.place_market_order(self.symbol, 'sell', self.hedge_qty)
            self.hedge_active = True
            self.logger.log(f"HEDGE OPEN qty={self.hedge_qty}@{price}", level="INFO")
        elif self.hedge_active and price > self.hedge_entry_price + atr:
            if self.exchange_sync and self.mode == "live":
                self.exchange_sync.place_market_order(self.symbol, 'buy', self.hedge_qty)
            pnl = (self.hedge_entry_price - price) * self.hedge_qty - (self.hedge_qty * price * self.futures_fee)
            self.realized_hedge_profit += pnl
            self.hedge_active = False
            self.logger.log(f"HEDGE CLOSE qty={self.hedge_qty}@{price}, PnL={pnl}", level="INFO")

    def get_summary(self) -> Dict:
        return {
            "Final USDT Balance": round(self.available_capital + self.reserve_capital, 2),
            "Realized Grid Profit (USDT)": round(self.realized_grid_profit, 2),
            "Realized Hedge Profit (USDT)": round(self.realized_hedge_profit, 2),
            "Open Grid Levels": [p for p, f in self.grid_state.items() if f],
            "Pending Positions": len(self.positions)
        }
