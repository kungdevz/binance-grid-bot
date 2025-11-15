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

from grid_bot.exchange import ExchangeSync
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
        self.futures_db     = FuturesOrders()
        self.acc_balance_db = AccountBalance()
        self.spot_orders_db  = SpotOrders()

        # --- runtime state ---
        self.positions: List[Dict[str, Any]] = []
        self.available_capital: float = 0.0
        self.realized_grid_profit: float = 0.0
        self.prev_close: Optional[float] = None

        # Initialize grid
        self.grid_group_id = ""
        self.grid_prices = {}
        self.grid_filled = {}

        if mode == "live":
            self.exchange_sync = ExchangeSync(
                symbol_spot=self.symbol,
                symbol_future=self.futures_symbol,
                mode="live",
            )
            self.spot    = self.exchange_sync.spot
            self.futures = self.exchange_sync.futures
            self._init_live_mode()
        elif self.mode == "backtest":
            self._init_back_test_mode()

    def _init_live_mode(self):

        # ดึง fee จาก env ก่อน (ง่ายสุด)
        self.spot_fee    = float(os.getenv("SPOT_FEE", 0.001))
        self.futures_fee = float(os.getenv("FUTURES_FEE", 0.0004))

        # Sync account balance
        balance = self.spot.fetch_balance()
        usdt_info = balance.get("USDT") or {}
        self.initial_capital = float(usdt_info.get("total", 0.0))
        self.logger.log(f"Live USDT balance fetched: {self.initial_capital}", level="INFO")

        # reserve/available สำหรับ live
        self.reserve_capital   = self.initial_capital * self.reserve_ratio
        self.available_capital = self.initial_capital - self.reserve_capital

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

    def _init_back_test_mode(self):
        self.initial_capital = float(os.getenv("INITIAL_CAPITAL", 10000))
        self.spot_fee        = float(os.getenv("SPOT_FEE", 0.001))
        self.futures_fee     = float(os.getenv("FUTURES_FEE", 0.0004))
        
        self.logger.log(f"Total capital: {self.initial_capital}", level="INFO")

        self.reserve_capital   = self.initial_capital * self.reserve_ratio
        self.available_capital = self.initial_capital - self.reserve_capital

        self.logger.log(f"Reserve capital set to {self.reserve_capital}", level="INFO")
        self.order_size_usdt = (self.initial_capital - self.reserve_capital) / self.grid_levels

        self.logger.log(f"Order size set to {self.order_size_usdt} USDT", level="INFO")
        self.exchange_sync = ExchangeSync(symbol_spot=self.symbol, symbol_future=self.futures_symbol, mode=self.mode)

        self.logger.log(f"Exchanges set for symbol spot: {self.symbol}, future spot: {self.futures_symbol}", level="DEBUG")
        self.acc_balance_db.insert_balance({
            "record_date": datetime.now().strftime("%Y-%m-%d"),
            "record_time": datetime.now().strftime("%H:%M:%S"),
            "start_balance_usdt":self.initial_capital,
            "end_balance_usdt": self.initial_capital,
            "notes" : "Initial back-test balance"
        })

    def run_from_file(self, file_path: str) -> Dict[str, Any]:
        """
        Read OHLCV CSV and execute backtest, CSV must have columns: Time, Open, High, Low, Close, Volume.
        """
        self.logger.log(f'Loading OHLCV data from {file_path}', level="INFO")
        df = pd.read_csv(file_path, parse_dates=['Time'])
        df.rename(columns={'Time':'time','Open':'Open','High':'High','Low':'Low','Close':'Close','Volume':'Volume'}, inplace=True)
        df.set_index('time', inplace=True)

        bootstrap_history = df.iloc[:100]
        base_price = bootstrap_history['Close'].iloc[-1]
        spacing = self.define_spacing_size(history=bootstrap_history, atr_period=self.atr_period)
        grid_id, grid_prices = self.initialize_grid(symbol=self.symbol, base_price=base_price,  spacing=spacing,  levels=self.grid_levels)
        self.place_initial_orders(order_size_usdt=self.order_size_usdt, grid_prices=grid_prices, grid_id=grid_id, center_price=base_price)

        for idx, row in df.iloc[100:].iterrows():
            ts = int(idx.value // 10**6)  # Timestamp → ms
            processed_row = self.on_candle(
                self.symbol,
                ts,
                float(row['Open']),
                float(row['High']),
                float(row['Low']),
                float(row['Close']),
                float(row['Volume']),
            )
            result = self._process_tick(self.symbol, processed_row)
        return result  

    def initialize_grid(self, symbol: str, base_price: float, spacing: float, levels: int = 10) -> Tuple[str, List[float]]:
        
        rows = self.grid_db.load_state_with_use_flgs(symbol, "Y")
        if rows and len(rows) >= levels * 2:
            self.grid_prices   = [float(r["grid_price"]) for r in rows]
            self.grid_group_id = rows[0]["group_id"]
            self.grid_filled = {
                float(r["grid_price"]): (r.get("status") == "open")  # ถ้า DB มี status ก็ใช้, ถ้าไม่มีจะเป็น False
                for r in rows
            }
            self.logger.log(
                f"Existing grid state found with group_id: {self.grid_group_id}, prices: {self.grid_prices}",
                level="INFO"
            )
        else:
            self.logger.log("No existing grid state found, initializing new grid", level="INFO")
            lower = [float(round(base_price - spacing * i, 2)) for i in range(1, levels+1)]
            upper = [float(round(base_price + spacing * i, 2)) for i in range(1, levels+1)]
            self.grid_prices   = upper + lower
            self.grid_group_id = util.generate_order_id("INIT")
            self.logger.log(
                f"Grid initialized with base price={base_price}, group_id={self.grid_group_id}, prices={self.grid_prices}",
                level="INFO"
            )
            self.grid_filled = {price: False for price in self.grid_prices}
            for price in self.grid_prices:
                items = {
                    'symbol': symbol,
                    'grid_price': price,
                    'use_status': 'Y',
                    'group_id': self.grid_group_id,
                    'base_price': float(base_price),
                    'spacing': float(spacing),
                    'date' : datetime.now().strftime('%Y-%m-%d'),
                    'time' : datetime.now().strftime('%H:%M:%S'),
                    'create_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                self.grid_db.save_state(items)

        return (self.grid_group_id, self.grid_prices)
    
    def define_spacing_size(self, atr_period: int, history: pd.DataFrame) -> float:
        df = history.copy().reset_index(drop=True)
        # 1. Calculate true range series
        tr = pd.concat([
            df['High'] - df['Low'],
            (df['High'] - df['Close'].shift()).abs(),
            (df['Low']  - df['Close'].shift()).abs()
        ], axis=1).max(axis=1)

        atr = tr.rolling(atr_period, min_periods=1).mean()
        df['TR'], df['ATR'] = tr, atr
        
        # 2. Track prev_close for first streaming candle
        self.prev_close = df['Close'].iloc[-1]

        # 3. Use last row to init grid
        last = df.iloc[-1]
        spacing = last['TR'] * (2.0 if last['TR'] > last['ATR'] else 1.0)
        return spacing
        
    def place_initial_orders(self, order_size_usdt : float, grid_prices : list[float], grid_id : str, center_price : float):
        resp = {}
        exchange = self.mode if self.mode == "live" else False
        for price in grid_prices:
            qty = round(order_size_usdt / float(price), 6)
            if price < center_price:
                resp = self.exchange_sync.place_limit_buy(self.symbol, price, qty, exchange)
                self.logger.log(f"Placed live limit buy for {qty}@{price}", level="INFO")
            else:
                resp = self.exchange_sync.place_limit_sell(self.symbol, price, qty, exchange)
                self.logger.log(f"Placed live limit sell for {qty}@{price}", level="INFO")

            order = self.spot_orders_db.get_order_by_grid_id_and_price(grid_id, price)
            if order is None:
                self.spot_orders_db.create_order(self.exchange_sync._build_spot_order_data(resp, grid_id))
        return resp

    def on_candle(self, symbol: str ,timestamp: int, open: float, high: float, low: float, close: float, volume: float) -> pd.Series:

        # 1) Indicator calculation.
        hist = self.ohlcv_db.get_recent_ohlcv(symbol, max(self.atr_period, 28))

        # 2) TR calculation.
        tr = self._calc_tr_single(high, low, close)
        tr_hist = hist['tr'].tolist() if not hist.empty else []
        tr_list_14 = (tr_hist + [tr])[-14:]
        tr_list_28 = (tr_hist + [tr])[-28:]
        atr_14 = float(np.mean(tr_list_14))
        atr_28 = float(np.mean(tr_list_28)) if tr_list_28 else atr_14

        # 3) EMA and ATR mean.
        atr_mean = atr_28
        if not hist.empty:
            prev = hist.iloc[-1]
            prev_ema = {
                "ema_14": prev["ema_14"],
                "ema_28": prev["ema_28"],
                "ema_50": prev["ema_50"],
                "ema_100": prev["ema_100"],
                "ema_200": prev["ema_200"]
            }
        else:
            prev_ema = {k: None for k in ["ema_14","ema_28","ema_50","ema_100","ema_200"]}

        ema_values = {}
        for name, period in self.ema_periods.items():
            alpha = 2 / (period + 1)
            prev_val = prev_ema[name]
            ema_values[name] = (
                close if prev_val is None else alpha * close + (1 - alpha) * prev_val
            )

        # 4) INSERT DB
        self.ohlcv_db.insert_ohlcv_data(
            symbol,
            timestamp,
            open,
            high,
            low,
            close,
            volume,
            tr,
            atr_14,
            atr_28,
            ema_values
        )

        # 5) Return grid logic
        return pd.Series({
            "timestamp": timestamp,
            "close": close,
            "atr": atr_14,
            "atr_mean": atr_mean,
            "ema_14": ema_values["ema_14"],
            "ema_28": ema_values["ema_28"],
            "ema_50": ema_values["ema_50"],
            "ema_100": ema_values["ema_100"],
            "ema_200": ema_values["ema_200"],
        }, name=timestamp)

    def _calc_tr_single(self, high: float, low: float, close: float) -> float:
        """
        Calculate TR for ONE candle. Uses self.prev_close for comparison, then updates it to the current close.
        The following formula to calculate the true range: TR = Max [(H-L),|H- Cp|,|L-Cp|] 
            where 
                H = Current Period High
                L = Current Period Low
                Cp = Previous Period Close
            so that True Range (TR) is the greatest of the following:
                (H-L)   = Current High less the current Low
                |H- Cp| = Current High less the previous Close (absolute value)
                |L-Cp|  = Current Low less the previous Close (absolute value)
        """

        if self.prev_close is None:
            tr = high - low
        else:
            tr1 = high - low
            tr2 = abs(high - self.prev_close)
            tr3 = abs(low  - self.prev_close)
            tr = max(tr1, tr2, tr3)
        self.prev_close = close
        return tr

    def _process_tick(self, symbol, row: pd.Series) -> None:
        price    = row['close']
        atr      = row['atr']
        atr_avg  = row['atr_mean']
        multiplier = 2.0 if atr > atr_avg else 1.0
        spacing    = atr * multiplier

        if self.mode == "live":
            try:
                self.sync_spot_orders_from_exchange()
            except Exception as e:
                self.logger.log(
                    f"sync_spot_orders_from_exchange in _process_tick error: {e}",
                    level="ERROR",
                )

        # BUY: ถ้าราคาลงมาแตะ grid ที่ยังไม่มี position
        for gp in self.grid_prices:
            filled = self.grid_filled.get(gp, False)
            if (price <= gp) and (not filled) and (self.available_capital >= self.order_size_usdt):
                self._buy_grid(timestamp=row['timestamp'], price=gp, spacing=spacing)

        # SELL: เช็ค position ที่เปิดอยู่
        self._check_sell(timestamp=row['timestamp'], price=price)

    def _check_sell(self, timestamp: int, price: float) -> None:
        """
        เช็คทุก position:
        - ถ้า price >= target → สร้างคำสั่ง SELL เพื่อปิด position
        - backtest/forward_test: สมมติ fill ทันที → อัปเดต available_capital + realized_grid_profit
        - live: ยิงคำสั่งจริงไปที่ exchange แล้วให้ระบบตาม fill ภายหลัง
        - อัปเดต in-memory grid_filled + spot_orders_db
        """
        remaining_positions: List[Dict[str, Any]] = []

        is_paper_mode = self.mode in ("backtest", "forward_test")
        has_spot_db   = hasattr(self, "spot_orders_db") and self.spot_orders_db is not None
        has_exch      = getattr(self, "exchange_sync", None) is not None

        grid_id = getattr(self, "grid_group_id", None) or "GRID"

        for pos in self.positions:
            qty     = pos["qty"]
            entry   = pos["entry"]
            target  = pos["target"]
            spacing = pos["spacing"]

            # ยังไม่ถึง target → เก็บ position ต่อ
            if price < target:
                remaining_positions.append(pos)
                continue

            # -------- 0) CHECK: มี SELL order ของ grid นี้อยู่แล้วหรือยังใน DB --------
            existing_sell = None
            if has_spot_db:
                try:
                    # ใช้ (grid_id, price) เป็น key; SELL จะถูกบันทึกด้วย side = 'SELL'
                    existing_sell = self.spot_orders_db.get_order_by_grid_id_and_price(grid_id, price)
                except Exception as e:
                    self.logger.log(
                        f"SpotOrdersDB check existing SELL error: {e}",
                        level="ERROR",
                    )

            if existing_sell:
                status = (existing_sell.get("status") or "").upper()
                side   = (existing_sell.get("side") or "").upper()
                if side == "SELL" and status in ("NEW", "PARTIALLY_FILLED"):
                    # มี SELL ค้างอยู่แล้ว → ไม่ต้องยิงซ้ำ
                    if hasattr(self, "grid_filled"):
                        self.grid_filled[entry] = False   # ถือว่าปล่อย grid นี้แล้ว
                    self.logger.log(
                        f"Skip _check_sell: existing SELL order grid_id={grid_id}, "
                        f"entry={entry}, price={price}, status={status}",
                        level="INFO",
                    )
                    continue

            # -------- 1) คำนวณ notional / fee / pnl --------
            notional = qty * price
            fee      = notional * self.spot_fee
            pnl      = notional - (qty * entry) - fee

            # -------- 2) PAPER MODE → fill ทันที --------
            if is_paper_mode:
                self.available_capital += (notional - fee)
                self.realized_grid_profit = getattr(self, "realized_grid_profit", 0.0) + pnl

            # -------- 3) LIVE MODE → ยิง SELL จริง --------
            exchange_resp = None
            if (self.mode == "live") and has_exch:
                try:
                    exchange_resp = self.exchange_sync.place_limit_sell(
                        symbol=self.symbol,
                        price=price,
                        qty=qty,
                        exchange=True,
                    )
                    self.logger.log(
                        f"[LIVE] Place limit SELL {qty} {self.symbol} @ {price} "
                        f"(entry={entry}, target={target}, pnl~{pnl})",
                        level="INFO",
                    )
                except Exception as e:
                    # ถ้า SELL ไม่ผ่าน → อย่า update grid_filled / DB ให้ถือว่ายังมี position
                    self.logger.log(f"Live SELL order error: {e}", level="ERROR")
                    remaining_positions.append(pos)
                    continue

            # -------- 4) เตรียม order_data เขียนลง SpotOrdersDB --------
            order_data = None
            if has_spot_db:
                try:
                    if exchange_resp is not None and hasattr(self.exchange_sync, "_build_spot_order_data"):
                        order_data = self.exchange_sync._build_spot_order_data(
                            exchange_resp,
                            grid_id=grid_id,
                        )
                        order_data["side"]  = "SELL"
                    else:
                        resp = self.exchange_sync.place_limit_sell(self.symbol, price, qty, False)
                        order_data = self.exchange_sync._build_spot_order_data(resp, grid_id=grid_id)
                        order_data["status"] = "FILLED" if is_paper_mode else "NEW"
                        order_data["type"] = "MARKET" if is_paper_mode else "LIMIT"
                        order_data["executed_qty"] = qty
                        order_data["cummulative_quote_qty"] = notional if is_paper_mode else 0.0
                        order_data["order_id"] = util.generate_order_id("SELL")

                except Exception as e:
                    self.logger.log(f"Build SELL order data error: {e}", level="ERROR")

            # -------- 5) เขียน SELL ลง DB --------
            if has_spot_db and order_data is not None:
                try:
                    self.spot_orders_db.create_order(order_data)
                except Exception as e:
                    self.logger.log(
                        f"SpotOrdersDB SELL create_order error: {e}", level="ERROR"
                    )

            # -------- 6) อัปเดต in-memory grid_filled --------
            if hasattr(self, "grid_filled"):
                # ตัว entry นี้ขายไปแล้ว → เปิดให้ BUY ใหม่ได้
                self.grid_filled[entry] = False

            # -------- 7) Log สรุปผล --------
            self.logger.log(
                f"Grid SELL: entry={entry}, sell_price={price}, qty={qty}, "
                f"notional={notional}, fee={fee}, pnl={pnl}, mode={self.mode}",
                level="DEBUG",
            )

        # -------- 8) เก็บ positions ที่ยังไม่ถึงเป้าไว้ต่อ --------
        self.positions = remaining_positions


    def _buy_grid(self, timestamp: int, price: float, spacing: float) -> None:
        """
        เปิด Grid Buy ที่ราคา `price`

        - backtest / forward_test:
            * สมมติว่า fill ทันที → หัก available_capital + create position ใน self.positions
            * เขียน order ลง spot_orders_db ด้วย status = FILLED

        - live:
            * เช็กก่อน:
                1) in-memory grid_filled
                2) exchange (open orders)
                3) spot_orders_db
            ถ้ามีอยู่แล้ว → ไม่ยิงซ้ำ
            * ถ้าไม่มี → ยิง limit BUY จริงไปที่ exchange
            * เขียน order ลง spot_orders_db (status จาก exchange)
            * ยังไม่หัก available_capital / ไม่สร้าง position จนกว่าจะมี fill handler
        """
        qty      = round(self.order_size_usdt / price, 6)
        notional = self.order_size_usdt
        fee      = notional * self.spot_fee
        target   = round(price + spacing, 4)
        now_ms   = timestamp

        is_paper_mode = self.mode in ("backtest", "forward_test")
        has_spot_db   = hasattr(self, "spot_orders_db") and self.spot_orders_db is not None
        has_exch      = getattr(self, "exchange_sync", None) is not None

        grid_id = getattr(self, "grid_group_id", None) or str(price)

        # ---------- 0) CHECK: in-memory flag ----------
        if hasattr(self, "grid_filled"):
            if self.grid_filled.get(price, False):
                self.logger.log(
                    f"Skip _buy_grid: grid price {price} already marked filled in memory",
                    level="DEBUG",
                )
                return

        # ---------- 1) CHECK: live mode → ถาม exchange ก่อน ----------
        if self.mode == "live" and has_exch:
            try:
                # ให้ ExchangeSync เช็คว่ามี open BUY ที่ grid นี้อยู่แล้วไหม
                ex_state = self.exchange_sync.sync_grid_state([price])  # {price: bool}
                if ex_state.get(price):
                    if hasattr(self, "grid_filled"):
                        self.grid_filled[price] = True
                    self.logger.log(
                        f"Skip _buy_grid: exchange reports existing BUY at price={price}",
                        level="INFO",
                    )
                    return
            except Exception as e:
                self.logger.log(f"Exchange sync_grid_state error: {e}", level="ERROR")

        # ---------- 2) CHECK: DB (spot_orders) ----------
        existing = None
        if has_spot_db:
            try:
                existing = self.spot_orders_db.get_order_by_grid_id_and_price(grid_id, price)
            except Exception as e:
                self.logger.log(f"SpotOrdersDB check existing order error: {e}", level="ERROR")

        if existing:
            status = (existing.get("status") or "").upper()
            side   = (existing.get("side") or "").upper() or "BUY"

            # ถ้ามี BUY ที่ยังไม่จบอยู่แล้ว ก็ไม่ต้องยิงซ้ำ
            if side == "BUY" and status in ("NEW", "PARTIALLY_FILLED"):
                if hasattr(self, "grid_filled"):
                    self.grid_filled[price] = True
                self.logger.log(f"Skip _buy_grid: existing DB order grid_id={grid_id}, price={price}, status={status}", level="INFO")
                return

        # ---------- 3) live mode → ยิง order จริง ----------
        exchange_resp = None
        if self.mode == "live" and has_exch:
            try:
                exchange_resp = self.exchange_sync.place_limit_buy(
                    symbol=self.symbol,
                    price=price,
                    qty=qty,
                    exchange=True,
                )
                self.logger.log(
                    f"[LIVE] Place limit BUY {qty} {self.symbol} @ {price} (grid_id={grid_id})",
                    level="INFO",
                )
            except Exception as e:
                self.logger.log(f"Live BUY order error: {e}", level="ERROR")
                return

        # ---------- 4) สร้าง order_data สำหรับเขียน DB ----------
        order_data = None
        try:
            if exchange_resp is not None and hasattr(self.exchange_sync, "_build_spot_order_data"):
                order_data = self.exchange_sync._build_spot_order_data(exchange_resp, grid_id=grid_id)
            else:
                resp = self.exchange_sync.place_limit_buy(self.symbol, price, qty, False)
                order_data = self.exchange_sync._build_spot_order_data(resp, grid_id=grid_id)
                order_data["status"] = "FILLED" if is_paper_mode else "NEW"
                exec_qty = qty if is_paper_mode else 0.0
                order_data["executed_qty"] = exec_qty
                order_data["cummulative_quote_qty"] = exec_qty * price
                order_data["order_id"] = util.generate_order_id("BUY")

        except Exception as e:
            self.logger.log(f"Build spot order data error: {e}", level="ERROR")

        # ---------- 5) เขียน order ลง DB ----------
        if has_spot_db and order_data is not None:
            try:
                self.spot_orders_db.create_order(order_data)
            except Exception as e:
                self.logger.log(f"SpotOrdersDB create_order error: {e}", level="ERROR")

        # ---------- 6) อัพเดต in-memory grid_filled ----------
        if hasattr(self, "grid_filled"):
            self.grid_filled[price] = True

        # ---------- 7) PAPER MODE → ถือว่า fill ทันที ----------
        if is_paper_mode:
            self.available_capital -= (notional + fee)
            self.positions.append(
                {
                    "qty":       qty,
                    "entry":     price,
                    "target":    target,
                    "spacing":   spacing,
                    "timestamp": timestamp,
                }
            )
            self.logger.log(
                f"[PAPER] Grid BUY filled @ {price}, target={target}, qty={qty}, fee={fee}",
                level="DEBUG",
            )
        else:
            self.logger.log(
                f"[LIVE] Grid BUY order placed @ {price}, qty={qty}, spacing={spacing} (waiting fill)",
                level="DEBUG",
            )

    def sync_spot_orders_from_exchange(self) -> None:
        """
        ดึงสถานะล่าสุดของ spot orders จาก exchange แล้ว sync กลับเข้า spot_orders DB
        - ใช้ใน live mode เท่านั้น
        - อัปเดต status, executed_qty, avg_price, binance_update_time ฯลฯ
        """
        if self.mode != "live":
            return

        if not hasattr(self, "exchange_sync"):
            return

        # 1) ดึง open orders จาก exchange
        try:
            open_orders = self.exchange_sync.fetch_open_orders()  # ccxt format
        except Exception as e:
            self.logger.log(f"sync_spot_orders_from_exchange: fetch_open_orders error: {e}", level="ERROR")
            return

        for o in open_orders:
            info = o.get("info", {})
            order_id = info.get("orderId")
            if not order_id:
                continue

            updates = {
                "status":                info.get("status"),
                "executed_qty":          info.get("executedQty"),
                "cummulative_quote_qty": info.get("cummulativeQuoteQty"),
                "binance_update_time":   info.get("updateTime"),
                "is_working":            int(info.get("isWorking", True)),
            }

            try:
                self.spot_orders_db.update_order(order_id=str(order_id), updates=updates)
            except Exception as e:
                self.logger.log(f"sync_spot_orders_from_exchange: update_order({order_id}) error: {e}", level="ERROR")
