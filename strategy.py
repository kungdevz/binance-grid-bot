from collections import deque
import os
import pandas as pd
import numpy as np
import utils.utils as ut
from typing import Any, Dict, List, Tuple, Optional

from database.future_orders_db import FuturesOrdersDB
from database.grid_states_db import GridStateDB
from database.spot_orders_db import SpotOrdersDB
from database.account_balance import AccountBalanceDB

from exchange import create_exchanges, ExchangeSync

from exchange import ExchangeSync
from logger import Logger

class USDTGridStrategy:
    def __init__(
         self,
        symbol: str,
        db_path: str = "database/schema/backtest_bot.db",
        atr_period: int = 14,
        atr_mean_window: int = 100,
        ema_periods: Dict[str, int] = None,
    ):
        # Basic configuration from .env
        self.symbol = symbol
        self.db_path = db_path
        self.atr_period = atr_period
        self.atr_mean_window = atr_mean_window
        self.ema_periods = ema_periods or {
            'ema_14': 14,
            'ema_28': 28,
            'ema_50': 50,
            'ema_100': 100,
            'ema_200': 200
        }

         # Mode and grid parameters
        self.mode = os.getenv("mode", "forward_test")                     # "forward_test" or "live"
        self.reserve_ratio = float(os.getenv("reserve_ratio", 0.3))       # Portion of capital reserved
        self.grid_levels = int(os.getenv("grid_levels", 5))               # Number of grid levels

        # Fees and initial capital will be loaded per mode
        self.spot_fee = 0.0
        self.futures_fee = 0.0
        self.initial_capital = 0.0

        # Logger
        self.logger = Logger(env=os.getenv("ENVIRONMENT", "development"), db_path=self.db_path)
        self.logger.log(f"Initializing strategy in {self.mode} mode", level="DEBUG")

        # Initialize databases
        self.spot_db = SpotOrdersDB(self.db_path)
        self.futures_db = FuturesOrdersDB(self.db_path)
        self.balance_db = AccountBalanceDB(self.db_path)
        self.grid_db = GridStateDB(self.db_path)

         # Initialize capital, exchanges, fees, balances, and positions
        self._init_capital_and_fees()
        if self.mode == "live":
            self._init_live_mode()
        else:
            self._init_forward_mode()

        # Common state reset
        self.reset()

    def _init_capital_and_fees(self):
        if self.mode == "forward_test":
            # Load test parameters from .env
            self.initial_capital = float(os.getenv("INITIAL_CAPITAL", 10000))
            self.spot_fee       = float(os.getenv("SPOT_FEE", 0.001))
            self.futures_fee    = float(os.getenv("FUTURES_FEE", 0.0004))
        else:
            # Live: we'll fetch capital and fees from the exchange
            self.initial_capital = None  # will set after fetching balance

    def _init_live_mode(self):
        # Connect to exchanges
        api_key    = os.getenv("API_KEY")
        api_secret = os.getenv("API_SECRET")
        spot, futures = create_exchanges(api_key, api_secret)
        self.set_exchanges(spot, futures, self.symbol, mode="live")

        # Fetch fees from exchange
        self.spot_fee    = self.spot.get_trade_fee()
        self.futures_fee = self.futures.get_trade_fee()

        # Sync account balance
        balance = self.spot.get_account_balance(asset="USDT")
        self.initial_capital = balance.total  # total USDT balance
        self.logger.log(f"Live USDT balance fetched: {self.initial_capital}", level="INFO")
        # Persist balance record
        self.balance_db.insert_balance(
            record_date=pd.Timestamp.now().date(),
            record_time=pd.Timestamp.now().time(),
            start_balance_usdt=self.initial_capital,
            end_balance_usdt=self.initial_capital,
            notes="Initial live balance"
        )

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
        self.data_file_path = os.getenv("data_file_path", "load_data_backtest/data/BTCUSDT_1D.csv")
        self.balance_db.insert_balance(
            record_date=pd.Timestamp.now().date(),
            record_time=pd.Timestamp.now().time(),
            start_balance_usdt=self.initial_capital,
            end_balance_usdt=self.initial_capital,
            notes="Initial forward-test balance"
        )

    def set_exchanges(self, spot: Any, futures: Any, symbol: str, mode: str = "forward_test"):
        self.spot = spot
        self.futures = futures
        self.symbol = symbol
        self.exchange_sync = ExchangeSync(spot, symbol)
        self.logger.log(f"Exchanges set for symbol {symbol}", level="DEBUG")

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
        self.bootstrap(df)
        for idx, row in df.iterrows():
            # convert pandas Timestamp to epoch ms
            ts = int(idx.value // 10**6)
            self.on_candle(ts, float(row['Open']), float(row['High']), float(row['Low']), float(row['Close']), float(row['Volume']))
        return self.get_summary()


    def load_grid_state(self):
        if self.mode == "forward_test" and self.db:
            self.grid_state = self.db.load_state()
            self.logger.log("Loaded grid state from SQLite", level="DEBUG")
        elif self.mode == "live" and self.exchange_sync and self.grid_initialized:
            self.grid_state = self.exchange_sync.sync_grid_state(self.grid_prices)
            self.logger.log("Synced grid state from exchange", level="DEBUG")
        else:
            self.grid_state = {}
            self.logger.log("Initialized empty grid state", level="DEBUG")        

    def initialize_grid(self, base_price: float, spacing: float, levels: int = 10):
        
        self.center_price = base_price
        self.spacing      = spacing
        
        lower = [float(round(base_price - spacing * i, 2)) for i in range(1, levels+1)]
        upper = [float(round(base_price + spacing * i, 2)) for i in range(1, levels+1)]

        self.grid_prices = lower + upper
        self.logger.log(f"Grid initialized with prices: {self.grid_prices}, Center price: {self.center_price}, Spacing: {spacing}", level="INFO")
        group_id = ut.generate_order_id('INIT')

        for price in self.grid_prices:
            db = GridStateDB(db_path=self.db_path)
            items = {
                'grid_price': price,
                'use_status': 'Y',
                'groud_id': group_id,
                'base_price': float(self.center_price),
                'spacing': float(self.spacing),
                'create_date': pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            db.save_state(items)
        
        self.logger.log("Saved grid state to SQLite", level="DEBUG")

    def bootstrap(self, history: pd.DataFrame):
        df = history.copy()
        # 1. calculate true range series
        tr = pd.concat([
            df['High'] - df['Low'],
            (df['High'] - df['Close'].shift()).abs(),
            (df['Low']  - df['Close'].shift()).abs()
        ], axis=1).max(axis=1)

        atr = tr.rolling(self.atr_period).mean()
        df['TR'], df['ATR'] = tr, atr
        
        # track prev_close for first streaming candle
        self.prev_close = df['Close'].iloc[-1]

        # use last row to init grid
        last = df.iloc[-1]
        spacing = last['TR'] * (2.0 if last['TR'] > last['ATR'] else 1.0)
        self.initialize_grid(last['Close'], spacing)
        self.place_initial_orders(self)

    def place_initial_orders(self) -> None:
        for price in self.grid_prices:
            qty = round(self.order_size_usdt / price, 6)
            if self.mode == "live" and self.exchange_sync:
                if price < self.center_price:
                    self.exchange_sync.place_limit_buy(self.symbol, price, qty)
                    self.logger.log(f"Placed live limit buy for {qty}@{price}", level="INFO")
                else:
                    self.exchange_sync.place_limit_sell(self.symbol, price, qty)
                    self.logger.log(f"Placed live limit sell for {qty}@{price}", level="INFO")
                self.grid_state[price] = 'open'
            elif self.mode == "forward_test":
                if price < self.center_price:
                    self.positions.append((qty, price, round(price + self.spacing, 2), self.spacing))
                    self.logger.log(f"Simulated open buy {qty}@{price}", level="INFO")
                if price > self.center_price:
                    self.positions.append((qty, price, round(price + self.spacing, 2), self.spacing))
                    self.logger.log(f"Simulated open sell {qty}@{price}", level="INFO")

    def on_candle(self, timestamp: int, open: float, high: float, low: float, close: float, volume: float) -> None:
        prev_df = self.db.get_recent_ohlcv(self.symbol, 1)
        if not prev_df.empty:
            prev_close = prev_df['close'].iloc[-1]
            prev_emas = {name: prev_df[name].iloc[-1] for name in self.ema_periods}
        else:
            prev_close = close
            prev_emas = {name: None for name in self.ema_periods}

        # คำนวณ TR และ ATR
        tr = self._calc_tr_single(high, low, prev_close)
        hist = self.db.get_recent_ohlcv(self.symbol, self.atr_period)['tr'].tolist()
        tr_list = (hist + [tr])[-self.atr_period:]
        atr_value = float(np.mean(tr_list))
        atr_mean = float(np.mean(tr_list))

        # คำนวณ EMA แต่ละช่วง
        emas: Dict[str, float] = {}
        for name, period in self.ema_periods.items():
            alpha = 2 / (period + 1)
            prev = prev_emas.get(name)
            emas[name] = float(close if prev is None else alpha * close + (1 - alpha) * prev)

        # บันทึกลงฐานข้อมูล
        self.db.insert_ohlcv_data(
            self.symbol,
            timestamp,
            open,
            high,
            low,
            close,
            volume,
            tr,
            atr_value,
            emas['ema_14'],
            emas['ema_28'],
            emas['ema_50'],
            emas['ema_100'],
            emas['ema_200']
        )

        # เตรียม row สำหรับ grid/hedge logic
        row = pd.Series({
            'timestamp': timestamp,
            'Close': close,
            'ATR': atr_value,
            'ATR_mean': atr_mean,
            **emas
        }, name=timestamp)
        # 5) ส่งต่อให้ logic หลักทำงาน
        self._process_tick(row)

    def _calc_tr_single(self, high: float, low: float, close: float) -> float:
        """
        คำนวณ True Range จาก high, low และ prev_close (float)
        แล้วอัปเดต self.prev_close เป็น close
        """
        # ถ้า prev_close ยัง None ให้ใช้ high-low
        if self.prev_close is None:
            tr = high - low
        else:
            tr1 = high - low
            tr2 = abs(high - self.prev_close)
            tr3 = abs(low  - self.prev_close)
            tr  = max(tr1, tr2, tr3)

        # เก็บ close ปัจจุบันไว้ใช้ครั้งถัดไป
        self.prev_close = close
        return tr

    def _process_tick(self, row: pd.Series) -> None:
        price = row['Close']
        atr = row['ATR']
        atr_avg = row['ATR_mean']
        multiplier = 2.0 if atr > atr_avg else 1.0
        spacing = atr * multiplier

        if not self.grid_initialized:
            self.initialize_grid(price, spacing)

        for gp in self.grid_prices:
            if price <= gp and not self.grid_state.get(gp, False) and self.available_capital >= self.order_size_usdt:
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
