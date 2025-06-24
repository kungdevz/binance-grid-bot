from collections import deque
import os
import pandas as pd
import numpy as np
from typing import Any, Dict, List, Tuple, Optional
from db import GridStateDB
from exchange import ExchangeSync
from logger import Logger

class USDTGridStrategy:
    def __init__(
        self,
        initial_capital: float = 10000,
        mode: str = "forward_test",
        db_path: str = "grid_state.db",
        spot_fee: float = 0.001,
        futures_fee: float = 0.0004,
        reserve_ratio: float = 0.3,
        order_size_usdt: float = 500,
        hedge_size_ratio: float = 0.5,
        grid_state_enabled: bool = True,
        atr_period: int = 14,
        atr_mean_window: int = 100,
        enivronment: str = "development"
    ):
        self.initial_capital = initial_capital
        self.mode = mode
        self.reserve_ratio = reserve_ratio
        self.order_size_usdt = order_size_usdt
        self.spot_fee = spot_fee
        self.futures_fee = futures_fee
        self.hedge_size_ratio = hedge_size_ratio
        self.grid_state_enabled = grid_state_enabled

        # ATR settings
        self.atr_period = atr_period
        self.atr_mean_window = atr_mean_window
        # Deques for streaming ATR & ATR_mean
        self.tr_history = deque(maxlen=self.atr_period)       # to compute ATR
        self.atr_history = deque(maxlen=self.atr_mean_window) # to compute ATR_mean
        self.prev_close: Optional[float] = None

        # setup logger
        self.logger = Logger(env=enivronment, db_path=db_path)
        self.logger.log(f"Initializing strategy in {enivronment} mode", level="DEBUG")

        # persistence & exchange placeholders
        self.db: Optional[GridStateDB] = None
        self.exchange_sync: Optional[ExchangeSync] = None
        if self.mode == "forward_test":
            self.db = GridStateDB(db_path)
            self.logger.log(f"GridStateDB initialized at {db_path}", level="DEBUG")

        # runtime state
        self.reset()

    def set_exchanges(self, spot: Any, futures: Any, symbol: str):
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
        self.spot_log = []
        self.futures_log = []
        self.tr_history.clear()
        self.atr_history.clear()
        self.prev_close = None
        self.logger.log("Strategy state reset", level="DEBUG")

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

    def save_grid_state(self):
        if self.mode == "forward_test" and self.db:
            self.db.save_state(self.grid_state)
            self.logger.log("Saved grid state to SQLite", level="DEBUG")

    def initialize_grid(self, base_price: float, spacing: float, levels: int = 3):
        self.grid_prices = [round(base_price - spacing * i, 2) for i in range(1, levels+1)]
        self.grid_initialized = True
        self.grid_state = {p: False for p in self.grid_prices}
        self.save_grid_state()
        self.logger.log(f"Grid initialized with prices: {self.grid_prices}", level="INFO")

        if self.mode == "live" and self.exchange_sync:
            for price in self.grid_prices:
                qty = round(self.order_size_usdt / price, 6)
                self.exchange_sync.place_limit_buy(self.symbol, price, qty)
                self.logger.log(f"Placed live limit buy for {qty}@{price}", level="INFO")
                self.grid_state[price] = True

    def bootstrap(self, history_df: pd.DataFrame):
        """
        1) คำนวณ full TR, ATR, ATR_mean บน history
        2) dropna หนึ่งครั้ง
        3) เติม deque ให้พร้อมสำหรับ streaming
        4) initialize_grid
        """
        df = history_df.copy()

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

        # fill deques
        self.tr_history.extend(tr.iloc[-self.atr_period:].tolist())
        self.atr_history.extend(atr.iloc[-self.atr_mean_window:].tolist())

        # track prev_close for first streaming candle
        self.prev_close = df['Close'].iloc[-1]

        # use last row to init grid
        last = df.iloc[-1]
        spacing = last['ATR'] * (2.0 if last['ATR'] > last['ATR_mean'] else 1.0)
        self.initialize_grid(last['Close'], spacing)
        self.logger.log(f"Bootstrapped grid at {last.name} price={last['Close']} spacing={spacing}", level="INFO")

    def on_candle(self, open: float, high: float, low: float, close: float, volumn: float) -> None:
        # คำนวณ True Range จากแท่งนี้
        tr = self._calc_tr_single(high, low, close)

        # คำนวณ ATR & ATR_mean จาก deque
        self.tr_history.append(tr)
        atr = float(np.mean(self.tr_history))
        self.atr_history.append(atr)
        atr_mean = float(np.mean(self.atr_history))

        # 4) สร้าง pd.Series สำหรับใช้กับ _process_tick
        row = pd.Series({
            'Close': close,
            'ATR':   atr,
            'ATR_mean': atr_mean
        })

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
        msg = f"Grid BUY {qty}@{price}, target={target}"
        self.logger.log(msg, level="INFO")
        self.spot_log.append((timestamp, 'buy', price, qty, target))
        self.grid_state[price] = True

    def _check_sell(self, timestamp, price: float) -> None:
        new_positions = []
        for qty, entry, target, spacing in self.positions:
            if price >= target:
                notional = qty * price
                fee = notional * self.spot_fee
                pnl = notional - (qty * entry) - fee
                self.available_capital += notional - fee
                self.realized_grid_profit += pnl
                msg = f"Grid SELL {qty}@{price}, entry={entry}, PnL={pnl}"
                self.logger.log(msg, level="INFO")
                self.spot_log.append((timestamp, 'sell', price, qty, entry, pnl))
                self.grid_state[entry] = False
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
            self.futures_log.append(('hedge_open', price, self.hedge_qty))
        elif self.hedge_active and price > self.hedge_entry_price + atr:
            if self.exchange_sync and self.mode == "live":
                self.exchange_sync.place_market_order(self.symbol, 'buy', self.hedge_qty)
            pnl = (self.hedge_entry_price - price) * self.hedge_qty - (self.hedge_qty * price * self.futures_fee)
            self.realized_hedge_profit += pnl
            self.hedge_active = False
            self.logger.log(f"HEDGE CLOSE qty={self.hedge_qty}@{price}, PnL={pnl}", level="INFO")
            self.futures_log.append(('hedge_close', price, self.hedge_qty, pnl))

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
