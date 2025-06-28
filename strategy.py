from collections import deque
import os
import pandas as pd
import numpy as np
import utils
from typing import Any, Dict, List, Tuple, Optional
from database.future_orders_db import FuturesOrdersDB
from database.grid_states_db import GridStateDB
from database.spot_orders_db import SpotOrdersDB

from exchange import create_exchanges, ExchangeSync

from exchange import ExchangeSync
from logger import Logger

class USDTGridStrategy:
    def __init__(
        self,
        symbol: str,
        db: Any,
        initial_capital: float = 10000,
        mode: str = "forward_test",
        db_path: str = "grid_state.db",
        atr_period: int = 14,
        atr_mean_window: int = 100,
        spot_fee: float = 0.001,
        futures_fee: float = 0.0004,
        reserve_ratio: float = 0.3,
        order_size_usdt: float = 500,
        hedge_size_ratio: float = 0.5,
        grid_state_enabled: bool = True,
        ema_periods: Dict[str, int] = None,
        enivronment: str = "development",
    ):
        self.initial_capital = initial_capital
        self.mode = mode
        self.reserve_ratio = reserve_ratio
        self.order_size_usdt = order_size_usdt
        self.spot_fee = spot_fee
        self.futures_fee = futures_fee
        self.hedge_size_ratio = hedge_size_ratio
        self.grid_state_enabled = grid_state_enabled
        self.db_path = db_path

        # ATR settings
        self.atr_period = atr_period
        self.atr_mean_window = atr_mean_window
        
        self.symbol = symbol
        self.atr_period = atr_period
        self.ema_periods = ema_periods or {
            'ema_14': 14,
            'ema_28': 28,
            'ema_50': 50,
            'ema_100': 100,
            'ema_200': 200
        }

        # setup logger
        self.logger = Logger(env=enivronment, db_path=db_path)
        self.logger.log(f"Initializing strategy in {enivronment} mode", level="DEBUG")
        self.reset()

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
        self.positions: List[Tuple[float, float, float, float]] = []
        self.grid_prices: List[float] = []
        self.grid_state: Dict[float, bool] = {}
        self.grid_initialized = False
        self.hedge_active = False
        self.hedge_entry_price = 0.0
        self.hedge_qty = 0.0
        self.prev_close = None
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

        group_id = utils.generate_order_id('INIT')
        for price in self.grid_prices:
            db = GridStateDB(db_path=self.db_path)
            items = {
                'grid_price': price,
                'use_status': 'Y',
                'groud_id': group_id
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

        # 2. rolling ATR & ATR_mean
        atr = tr.rolling(self.atr_period).mean()
        atr_mean = atr.rolling(self.atr_mean_window).mean()
        df['ATR'], df['ATR_mean'] = atr, atr_mean

        df = df.dropna()
        if df.empty:
            self.logger.log("Not enough history to bootstrap", level="WARNING")
            return
        
        # track prev_close for first streaming candle
        self.prev_close = df['Close'].iloc[-1]

        # use last row to init grid
        last = df.iloc[-1]
        spacing = last['ATR'] * (2.0 if last['ATR'] > last['ATR_mean'] else 1.0)
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

    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        tr = pd.concat([
            df['High'] - df['Low'],
            (df['High'] - df['Close'].shift()).abs(),
            (df['Low'] - df['Close'].shift()).abs()
        ], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    def get_summary(self) -> Dict:
        return {
            "Final USDT Balance": round(self.available_capital + self.reserve_capital, 2),
            "Realized Grid Profit (USDT)": round(self.realized_grid_profit, 2),
            "Realized Hedge Profit (USDT)": round(self.realized_hedge_profit, 2),
            "Open Grid Levels": [p for p, f in self.grid_state.items() if f],
            "Pending Positions": len(self.positions)
        }
