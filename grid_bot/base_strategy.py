# base_strategy.py
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

import pandas as pd
import numpy as np

from grid_bot.database.grid_states import GridState
from grid_bot.database.ohlcv_data import OhlcvData
from grid_bot.database.spot_orders import SpotOrders
from grid_bot.database.future_orders import FuturesOrders
from grid_bot.database.account_balance import AccountBalance
from grid_bot.database.logger import Logger

from grid_bot.datas.position import Position
import grid_bot.utils.util as util

class BaseGridStrategy(ABC):
    """
    Base class : รวม logic ที่ใช้ร่วมกันสำหรับ Live และ Backtest
    ไม่ผูกกับ ccxt หรือ exchange ใด ๆ โดยตรง
    """

    def __init__(
        self,
        symbol: str,
        symbol_future: str,
        initial_capital: float,
        grid_levels: int,
        atr_multiplier: float,
        order_size_usdt: float,
        reserve_ratio: float,
        mode: str,
        logger: Optional[Logger] = None,
    ) -> None:
        self.symbol = symbol
        self.symbol_future = symbol_future
        self.mode = mode

        # Money
        self.initial_capital   = float(initial_capital)
        self.reserve_ratio     = float(reserve_ratio)
        self.order_size_usdt   = float(order_size_usdt)
        self.total_capital     = float(initial_capital)
        self.reserve_capital   = self.total_capital * self.reserve_ratio
        self.available_capital = self.total_capital - self.reserve_capital

        # Grid config
        self.grid_levels     = int(grid_levels)
        self.atr_multiplier  = float(atr_multiplier)
        self.grid_prices: List[float] = []
        self.grid_filled: Dict[float, bool] = {}       # grid_price -> bool
        self.grid_group_id: Optional[str] = None
        self.grid_spacing: float = 0.0                 # ระยะห่าง grid ปัจจุบัน (ใช้ทั้ง init+recalc)

        # tuning parameter สำหรับ recalc
        self.vol_up_ratio: float = 1.5    # ATR14 > ATR28 * 1.5 → ถือว่าผันผวนสูง
        self.vol_down_ratio: float = 0.7  # ATR14 < ATR28 * 0.7 → ถือว่านิ่งลง
        self.drift_k: float = 2.5         # price เลยกรอบเดิม k ช่อง → recenter ใหม่

        # state runtime
        self.positions: List[Position] = []
        self.realized_grid_profit: float = 0.0
        self.prev_close: Optional[float] = None

        # DB
        self.grid_db        = GridState()
        self.ohlcv_db       = OhlcvData()
        self.spot_orders_db = SpotOrders()
        self.futures_db     = FuturesOrders()
        self.acc_balance_db = AccountBalance()

        self.logger = logger or Logger()
        self.logger.log(
            f"[BaseGridStrategy] Init mode={mode}, symbol={symbol}, capital={self.total_capital}",
            level="INFO"
        )

    # ------------------------------------------------------------------
    # Abstract “I/O” methods – ให้ subclass ไป implement
    # ------------------------------------------------------------------

    @abstractmethod
    def _io_place_spot_buy(
        self,
        timestamp_ms: int,
        price: float,
        qty: float,
        grid_id: str,
    ) -> Dict[str, Any]:
        """
        ให้ subclass live/backtest ไป implement:
        - live: เรียก ExchangeSync.place_limit_buy + เขียน DB
        - backtest: จำลอง fill ทันที + เขียน DB (ถ้าต้องการ)
        return: ข้อมูล order ที่อยากเก็บ (order_id ฯลฯ)
        """
        raise NotImplementedError

    @abstractmethod
    def _io_place_spot_sell(
        self,
        timestamp_ms: int,
        position: Position,
        sell_price: float,
    ) -> Dict[str, Any]:
        """
        ให้ subclass ไป implement:
        - live: ยิง sell ไปที่ exchange (limit/market แล้วแต่ design)
        - backtest: จำลอง fill ทันที
        """
        raise NotImplementedError

    @abstractmethod
    def _io_open_hedge(self,
        timestamp_ms: int,
        notional_usdt: float,
        price: float,
    ) -> Optional[Dict[str, Any]]:
        """เปิด short hedge (ใช้ได้เฉพาะบางโหมด หรือ backtest จะ simulate ก็ได้)"""
        raise NotImplementedError

    @abstractmethod
    def _io_close_hedge(
        self,
        timestamp_ms: int,
    ) -> Optional[Dict[str, Any]]:
        """ปิด short hedge ทั้งหมด หรือบางส่วน ตาม logic ของ subclass"""
        raise NotImplementedError
    
    @abstractmethod
    def _run(
        self, 
        timestamp_ms: int
    ) -> None:
        raise NotImplementedError
    
    # ------------------------------------------------------------------
    # Common Logic
    # ------------------------------------------------------------------
    def _calc_tr_single(
        self,
        high: float,
        low: float,
        prev_close: Optional[float],
    ) -> float:
        """
        True Range (TR) ต่อ 1 แท่ง:
        TR = max(H-L, |H-Cp|, |L-Cp|)
        ถ้าไม่มี previous close (แท่งแรก) → ใช้แค่ H-L
        """
        if prev_close is None:
            return float(high - low)

        tr1 = high - low
        tr2 = abs(high - prev_close)
        tr3 = abs(low  - prev_close)
        return float(max(tr1, tr2, tr3))

    def _calc_atr_from_history(
        self,
        tr_hist: List[float],
        tr_current: float,
        periods: Tuple[int, ...] = (14, 28),
    ) -> Dict[int, float]:
        """
        คำนวณ ATR หลาย period จาก
        - tr_hist: list ของ TR ย้อนหลัง
        - tr_current: TR ของแท่งปัจจุบัน
        return: {period: atr_value}
        """
        all_tr = tr_hist + [tr_current]
        atr_values: Dict[int, float] = {}

        for p in periods:
            window = all_tr[-p:]
            atr_values[p] = float(np.mean(window)) if window else 0.0

        return atr_values
    
    def _calc_ema_from_history(
        self,
        hist: pd.DataFrame,
        close: float,
        periods: Tuple[int, ...] = (14, 28, 50, 100, 200),
    ) -> Dict[str, float]:
        """
        คำนวณ EMA หลาย period จากข้อมูลแท่งล่าสุดใน hist + close ปัจจุบัน
        ถ้ายังไม่มีค่า EMA เดิม → ใช้ close ปัจจุบันเป็นค่าเริ่มต้น
        """
        if not hist.empty:
            prev = hist.iloc[-1]
        else:
            prev = None

        ema_values: Dict[str, float] = {}

        for period in periods:
            col_name = f"ema_{period}"
            alpha = 2 / (period + 1)

            if prev is None or col_name not in prev or pd.isna(prev[col_name]):
                # แท่งแรก → seed ด้วย close ปัจจุบัน
                ema_values[col_name] = float(close)
            else:
                prev_val = float(prev[col_name])
                ema_values[col_name] = float(alpha * close + (1 - alpha) * prev_val)

        return ema_values
    
    from typing import Dict, Tuple

    def _calc_atr_ema_from_df(
        self,
        df: pd.DataFrame,
        atr_periods: Tuple[int, ...] = (14, 28),
        ema_periods: Tuple[int, ...] = (14, 28, 50, 100, 200),
    ) -> Dict[str, float]:
        """
        รับ df (ที่มี high, low, close ครบ และรวมแท่งปัจจุบันแล้ว)
        คืนค่าตัวชี้วัดล่าสุดของแท่งสุดท้าย:
        - tr
        - atr_<period>
        - ema_<period>
        """

        if df.empty:
            # ไม่มีข้อมูลเลย → คืน 0 ไปก่อน
            vals: Dict[str, float] = {"tr": 0.0}
            for p in atr_periods:
                vals[f"atr_{p}"] = 0.0
            for p in ema_periods:
                vals[f"ema_{p}"] = 0.0
            return vals

        # 1) TR series
        tr_series = self._calc_tr_series(df)
        tr_last = float(tr_series.iloc[-1])

        result: Dict[str, float] = {"tr": tr_last}

        # 2) ATR
        for p in atr_periods:
            if len(tr_series) >= p:
                atr_val = float(tr_series.rolling(p).mean().iloc[-1])
            else:
                atr_val = float(tr_series.mean())  # หรือ 0.0 แล้วแต่สไตล์คุณ
            result[f"atr_{p}"] = atr_val

        # 3) EMA (ใช้ pandas ewm จาก close ทั้งชุด)
        close = df["close"].astype(float)
        for p in ema_periods:
            ema_last = float(close.ewm(span=p, adjust=False).mean().iloc[-1])
            result[f"ema_{p}"] = ema_last

        return result
    
    def _calc_tr_series(self, df: pd.DataFrame) -> pd.Series:
        """
        คืนค่า pandas Series ของ TR สำหรับทุกแท่งใน df
        df ต้องมีคอลัมน์: high, low, close
        """

        if df.empty:
            return pd.Series(dtype=float)

        high  = df["high"].astype(float)
        low   = df["low"].astype(float)
        close = df["close"].astype(float)

        # previous close
        prev_close = close.shift(1)

        # TR components
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()

        # True Range = max(tr1, tr2, tr3)
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # แท่งแรกไม่มี prev_close, ให้ TR = high - low
        tr.iloc[0] = tr1.iloc[0]

        return tr

    def _calc_atr_ema(
        self,
        timestamp: float,
        open: float,
        close: float,
        high: float,
        low: float,
        volume: float,
        hist_df: Optional[pd.DataFrame] = None,
    ) -> int:
        """
        Engine กลางสำหรับ:
        - TR
        - ATR(14, 28)
        - EMA(14, 28, 50, 100, 200)
        แล้ว insert ลง ohlcv_db

        แหล่งข้อมูล:
        - ถ้า hist_df ไม่ว่าง → ใช้ hist_df (จากไฟล์ backtest) + append แท่งปัจจุบัน
        - ถ้า hist_df ว่าง → ใช้ history จาก DB แล้วต่อท้ายแท่งปัจจุบัน
        """

        # ------------------------------------------------------------------
        # 1) เตรียม DataFrame source
        # ------------------------------------------------------------------
        if hist_df is not None and not hist_df.empty:
            # ใช้ hist_df จาก backtest + append แท่งปัจจุบันเข้าไป
            hist = hist_df.copy()

            # ensure numeric
            for c in ["open", "high", "low", "close", "volume"]:
                if c in hist.columns:
                    hist[c] = hist[c].astype(float)

            current_row = pd.DataFrame(
                [{
                    "open":   float(open),
                    "high":   float(high),
                    "low":    float(low),
                    "close":  float(close),
                    "volume": float(volume),
                }],
                index=[timestamp],   # ใช้ timestamp เป็น index
            )

            df_src = pd.concat([hist, current_row], axis=0)
        else:
            # เคส live หรือไม่มี hist_df → ใช้ DB แทน
            hist = self.ohlcv_db.get_recent_ohlcv(self.symbol, 200)

            current_row = pd.DataFrame(
                [{
                    "time":   timestamp,
                    "open":   float(open),
                    "high":   float(high),
                    "low":    float(low),
                    "close":  float(close),
                    "volume": float(volume),
                }]
            ).set_index("time")

            if hist is not None and not hist.empty:
                # ensure numeric
                for c in ["open", "high", "low", "close", "volume"]:
                    if c in hist.columns:
                        hist[c] = hist[c].astype(float)

                df_src = pd.concat([hist, current_row], axis=0)
            else:
                df_src = current_row

        # ------------------------------------------------------------------
        # 2) คำนวณ TR / ATR / EMA จาก df_src
        # ------------------------------------------------------------------
        vals = self._calc_atr_ema_from_df(df_src)

        tr      = float(vals["tr"])
        atr_14  = float(vals["atr_14"])
        atr_28  = float(vals["atr_28"])
        ema_14  = float(vals["ema_14"])
        ema_28  = float(vals["ema_28"])
        ema_50  = float(vals["ema_50"])
        ema_100 = float(vals["ema_100"])
        ema_200 = float(vals["ema_200"])

        # ------------------------------------------------------------------
        # 3) INSERT ลง DB (1 row ของแท่งปัจจุบัน)
        # ------------------------------------------------------------------
        rowcount = self.ohlcv_db.insert_ohlcv_data(
            symbol   = self.symbol,
            timestamp= int(timestamp),
            open     = float(open),
            high     = float(high),
            low      = float(low),
            close    = float(close),
            volume   = float(volume),
            tr       = float(tr),
            atr_14   = float(atr_14),
            atr_28   = float(atr_28),
            ema_14   = float(ema_14),
            ema_28   = float(ema_28),
            ema_50   = float(ema_50),
            ema_100  = float(ema_100),
            ema_200  = float(ema_200),
        )

        return rowcount
    
    def _maybe_recenter_grid(
            self,
            timestamp_ms: int,
            price: float,
            atr_14: float,
            atr_28: float,
        ) -> None:
            """
            Hard rebuild:
            - เมื่อราคาออกนอกกรอบเดิมหลายช่อง หรือกริดถูกใช้ไปเกือบหมด
            - จะเลื่อนหน้าต่าง grid ให้ไปอยู่ใกล้ราคาปัจจุบันมากขึ้น (lower-only grid)
            """
            if not self.grid_prices:
                return

            spacing = self.grid_spacing
            if spacing <= 0 and len(self.grid_prices) >= 2:
                spacing = float(self.grid_prices[1] - self.grid_prices[0])
            if spacing <= 0 and atr_14 > 0:
                spacing = atr_14 * self.atr_multiplier
            if spacing <= 0:
                # ไม่มีข้อมูลพอจะตัดสินใจ
                return

            lowest = min(self.grid_prices)
            highest = max(self.grid_prices)

            # ดูว่าใช้ grid ไปแล้วกี่ level
            filled_levels = sum(1 for p in self.grid_prices if self.grid_filled.get(p, False))
            fill_ratio = filled_levels / len(self.grid_prices) if self.grid_prices else 0.0

            need_recenter = False
            reason = ""

            # 1) ราคาออกนอกกรอบหลายช่อง
            if price > highest + spacing * self.drift_k:
                need_recenter = True
                reason = f"price above window (>{self.drift_k} * spacing)"
            elif price < lowest - spacing * self.drift_k:
                need_recenter = True
                reason = f"price below window (>{self.drift_k} * spacing)"

            # 2) ใช้ grid ไปเยอะมาก (เช่นซื้อฝั่งล่างเกือบหมด)
            elif fill_ratio > 0.7:
                need_recenter = True
                reason = f"filled_levels={fill_ratio:.2%}"

            if not need_recenter:
                return

            # ----- สร้าง grid ใหม่รอบราคาปัจจุบัน -----
            # center ใหม่: ใช้ price เป็นหลักก่อน (จะไปผูกกับ EMA50 ก็ได้)
            new_center = float(price)

            # spacing ใหม่จาก ATR ปัจจุบัน
            new_spacing = spacing
            if atr_14 > 0:
                new_spacing = atr_14 * self.atr_multiplier

            if new_spacing <= 0:
                new_spacing = spacing  # fallback

            new_prices = [
                round(new_center - new_spacing * (i + 1), 4)
                for i in range(self.grid_levels)
            ]
            new_prices = sorted(new_prices)

            new_group_id = util.generate_order_id("INIT")
            now = datetime.now()
            now_date = now.strftime("%Y-%m-%d")
            now_time = now.strftime("%H:%M:%S")
            now_dt   = now.strftime("%Y-%m-%d %H:%M:%S")

            # เขียน state grid ใหม่ลง DB (ไม่ไปยุ่งของเก่า – แยก group_id)
            for p in new_prices:
                item = {
                    "symbol":     self.symbol,
                    "grid_price": float(p),
                    "use_status": "Y",
                    "group_id":   new_group_id,
                    "base_price": float(new_center),
                    "spacing":    float(new_spacing),
                    "date":       now_date,
                    "time":       now_time,
                    "create_date": now_dt,
                    "status":     "open",
                }
                try:
                    self.grid_db.save_state(item)
                except Exception as e:
                    self.logger.log(f"[GRID] save_state error during recenter: {e}", level="ERROR")

            # อัปเดต runtime state ให้ใช้ชุดใหม่
            self.grid_group_id = new_group_id
            self.grid_prices   = new_prices
            self.grid_spacing  = float(new_spacing)
            self.grid_filled   = {p: False for p in new_prices}

            self.logger.log(
                f"[GRID] recentered around {new_center} (reason={reason}), "
                f"spacing={new_spacing}, prices={new_prices}",
                level="INFO",
            )

    def _recalc_spacing_if_needed(self, atr_14: float, atr_28: float) -> float:
        """
        Soft adjust spacing :
        - ใช้ ATR14 เทียบกับ ATR28 เพื่อตัดสินใจว่าจะขยาย/หด grid หรือไม่
        - ถ้าไม่เปลี่ยนถือว่าใช้ spacing เดิม
        """
        if atr_14 <= 0 or atr_28 <= 0 or not self.grid_prices:
            return self.grid_spacing

        # old_spacing: ใช้อันที่เคยเซ็ตไว้ ถ้าไม่มีลองคำนวณจาก grid จริง
        old_spacing = self.grid_spacing
        if old_spacing <= 0 and len(self.grid_prices) >= 2:
            old_spacing = float(self.grid_prices[1] - self.grid_prices[0])

        if old_spacing <= 0:
            # fallback ถ้ายังไม่มีอะไรเลย
            old_spacing = atr_14 * self.atr_multiplier

        new_spacing = old_spacing

        # volatility regime
        if atr_14 > atr_28 * self.vol_up_ratio:
            # ตลาดผันผวนมาก → ขยายระยะห่าง grid
            new_spacing = atr_14 * self.atr_multiplier * 2.0
        elif atr_14 < atr_28 * self.vol_down_ratio:
            # ตลาดสงบ → หด grid ลง
            new_spacing = atr_14 * self.atr_multiplier * 1.0

        # ถ้าต่างไม่ถึง 20% จะไม่ปรับ เพื่อลด churn
        if old_spacing > 0 and abs(new_spacing - old_spacing) / old_spacing < 0.2:
            return old_spacing

        self.grid_spacing = float(new_spacing)
        self.logger.log(
            f"[GRID] spacing adjusted from {old_spacing:.4f} to {new_spacing:.4f} "
            f"(ATR14={atr_14:.4f}, ATR28={atr_28:.4f})",
            level="INFO",
        )
        return self.grid_spacing

    def _init_lower_grid(self, base_price: float, atr: float) -> None:
        """
        Create LOWER-only grid (the requirement USDT-only buy low and sell high at the base price)
        """
        if atr <= 0:
            spacing = base_price * 0.03  # fallback 3%, If the ATR value is less than 0 
        else:
            spacing = atr * self.atr_multiplier

        # เก็บ spacing ปัจจุบันไว้ใช้ตอน recalc
        self.grid_spacing = float(spacing)

        # คำนวณราคากริดด้านล่าง
        self.grid_prices = [
            round(base_price - spacing * (i + 1), 4)
            for i in range(self.grid_levels)
        ]
        
        self.grid_prices = sorted(self.grid_prices)
        self.grid_group_id = util.generate_order_id("INIT")
        self.grid_filled   = {p: False for p in self.grid_prices}

        now_date = datetime.now().strftime('%Y-%m-%d')
        now_time = datetime.now().strftime('%H:%M:%S')
        now_dt   = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        for price in self.grid_prices:
            item = {
                'symbol': self.symbol,
                'grid_price': price,
                'use_status': 'Y',
                'group_id': self.grid_group_id,
                'base_price': float(base_price),
                'spacing': float(spacing),
                'date': now_date,
                'time': now_time,
                'create_date': now_dt,
                'status': 'open',
            }
            self.grid_db.save_state(item)

        self.logger.log(
            f"Grid initialized (LOWER only) base={base_price}, group={self.grid_group_id}, prices={self.grid_prices}",
            level="INFO"
        )

    # ------------------------------------------------------------------
    # High-level event : on_bar / on_price
    # ------------------------------------------------------------------
    def on_bar(
            self,
            timestamp_ms: int,
            open_price: float,
            high: float,
            low: float,
            close: float,
            volume: float,
            hist_df: Optional[pd.DataFrame] = None,
        ) -> None:

        # Calculate TR, ATR and EMA Indicator and INSERT into DB.
        self._calc_atr_ema(
            timestamp=timestamp_ms,
            open=open_price,
            close=close,
            high=high,
            low=low,
            volume=volume,
            hist_df=hist_df,
        )

        price = float(close)

        # 1) ดึง ATR ล่าสุดจาก ohlcv_data
        last = self.ohlcv_db.get_recent_ohlcv(self.symbol, 1)
        if not last.empty:
            atr_14 = float(last.iloc[-1]["atr_14"])
            atr_28 = float(last.iloc[-1]["atr_28"])
        else:
            atr_14 = 0.0
            atr_28 = 0.0

        # 2) โหลด grid state จาก DB ถ้ายังไม่มีค่าใน memory
        if not self.grid_prices:
            rows = self.grid_db.load_state_with_use_flgs(self.symbol, "Y")
            if rows:
                self.grid_prices   = [float(r["grid_price"]) for r in rows]
                self.grid_group_id = rows[0]["group_id"]
                # ถ้าไม่มี status ให้ default เป็น False
                self.grid_filled = {
                    float(r["grid_price"]): (r.get("status") == "open")
                    for r in rows
                }
                # พยายามคาด spacing จากข้อมูลจริง
                if len(self.grid_prices) >= 2:
                    self.grid_spacing = float(self.grid_prices[1] - self.grid_prices[0])

        # 3) ถ้ายังไม่มี grid (ครั้งแรกจริง ๆ) → init จาก ATR
        if not self.grid_prices:
            self._init_lower_grid(base_price=price, atr=atr_14)
        else:
            # 3.1 ปรับ spacing ตาม volatility regime (soft adjust)
            self._recalc_spacing_if_needed(atr_14=atr_14, atr_28=atr_28)

            # 3.2 พิจารณาว่าควร recenter grid ใหม่ไหม (hard rebuild)
            self._maybe_recenter_grid(
                timestamp_ms=timestamp_ms,
                price=price,
                atr_14=atr_14,
                atr_28=atr_28,
            )

        # 4) Process buy / sell / hedge ต่อ
        self._process_buy_grid(timestamp_ms, price)
        self._process_sell_grid(timestamp_ms, price)
        self._process_hedge(timestamp_ms, price)

    # ------------------------------------------------------------------
    # BUY logic
    # ------------------------------------------------------------------
    def _process_buy_grid(self, timestamp_ms: int, price: float) -> None:
        """
        ถ้าราคาลงมาชน grid และมีทุน → เปิด position
        """
        for level_price in self.grid_prices:
            filled = self.grid_filled.get(level_price, False)

            if price <= level_price and not filled:
                if self.available_capital < self.order_size_usdt:
                    self.logger.log(f"Skip BUY grid@{level_price}: insufficient capital ({self.available_capital})", level="INFO")
                    continue

                qty = round(self.order_size_usdt / level_price, 6)

                order_info = self._io_place_spot_buy(
                    timestamp_ms=timestamp_ms,
                    price=level_price,
                    qty=qty,
                    grid_id=self.grid_group_id or "",
                )

                fee = 0.001
                notional = level_price * qty
                self.available_capital -= (notional + fee)

                # --- คำนวณ target ตาม ATR-based spacing ---
                # 1) ใช้ spacing ปัจจุบันที่มาจาก ATR * atr_multiplier
                spacing = getattr(self, "grid_spacing", 0.0)

                # 2) ถ้า spacing ยังไม่ถูกเซ็ต (เช่น เพิ่ง start) ให้ลองเดาจากระยะห่าง grid จริง
                if (not spacing) and len(self.grid_prices) >= 2:
                    spacing = abs(self.grid_prices[1] - self.grid_prices[0])

                # 3) ถ้ายังไม่มีข้อมูลเลย ค่อย fallback เป็น 2% (กันเคสฉุกเฉิน)
                if not spacing:
                    spacing = level_price * 0.02

                # target = entry + spacing (ATR-based)
                target = round(level_price + spacing, 4)

                pos = Position(
                    symbol=self.symbol,
                    side="LONG",
                    entry_price=level_price,
                    qty=qty,
                    grid_price=level_price,
                    target_price=target,
                    opened_at=timestamp_ms,
                    group_id=self.grid_group_id or "",
                    meta={"order": order_info},
                )

                self.positions.append(pos)
                self.grid_filled[level_price] = True

                self.logger.log(
                    f"Grid BUY filled @ {level_price} qty={qty}, target={target}, remaining_cap={self.available_capital}",
                    level="INFO",
                )

                # Snapshot account_balance (It's support only in the backtest/forward_test mode.)
                self._snapshot_account_balance(
                    timestamp_ms=timestamp_ms,
                    current_price=price,
                    notes=f"BUY @ {level_price}",
                )

    # ------------------------------------------------------------------
    # SELL logic
    # ------------------------------------------------------------------
    def _process_sell_grid(self, timestamp_ms: int, price: float) -> None:
        """
        ถ้าราคาขึ้นถึง target ของ position → ขายออก

        - ใช้ target_price ที่ถูกตั้งตอน BUY จาก ATR-based spacing
        - backtest / forward_test:
            * สมมติว่า SELL fill ทันทีที่ราคา `price`
            * อัปเดต available_capital และ realized_grid_profit
            * snapshot account_balance ไว้ใช้วิเคราะห์ภายหลัง
        - live:
            * เรียก _io_place_spot_sell ให้ subclass ไปยิงคำสั่งจริง
            * ไม่อัปเดต available_capital / realized_grid_profit ตรง ๆ
              (ให้ไปดึงจาก exchange/DB ภายหลังเพื่อความตรง)
        """
        remaining_positions: List[Position] = []
        is_paper_mode = self.mode in ("backtest", "forward_test")

        for pos in self.positions:
            # ยังไม่ถึง target → ถือไว้ต่อ
            if price < pos.target_price:
                remaining_positions.append(pos)
                continue

            # ----- Trigger SELL ผ่าน I/O layer -----
            order_info = self._io_place_spot_sell(
                timestamp_ms=timestamp_ms,
                position=pos,
                sell_price=price,
            )

            # คำนวณ notional / fee / pnl แบบ generic
            notional = price * pos.qty
            fee = 0.0  # TODO: จะไปดึงจาก order_info หรือ self.spot_fee ภายหลังได้
            pnl = (price - pos.entry_price) * pos.qty - fee

            if is_paper_mode:
                # backtest/forward_test → สมมติ fill ทันที
                self.available_capital += (notional - fee)
                self.realized_grid_profit += pnl

                self.logger.log(
                    f"[PAPER] Grid SELL: entry={pos.entry_price}, "
                    f"target={pos.target_price}, sell={price}, "
                    f"qty={pos.qty}, pnl={pnl}, "
                    f"total_realized={self.realized_grid_profit}",
                    level="INFO",
                )
            else:
                # live → แค่บันทึกว่าได้สั่งขายแล้ว (ให้ไปดู fill จริงจาก exchange/DB)
                self.logger.log(
                    f"[LIVE] Grid SELL order placed: entry={pos.entry_price}, "
                    f"target={pos.target_price}, sell={price}, "
                    f"qty={pos.qty}, est_pnl≈{pnl}",
                    level="INFO",
                )

            # ----- ปลดล็อก grid level นี้ ให้เปิด BUY ใหม่ได้ -----
            try:
                self.grid_filled[pos.grid_price] = False
            except Exception as e:
                self.logger.log(
                    f"[GRID] grid_filled update error for price={pos.grid_price}: {e}",
                    level="ERROR",
                )

            # ----- snapshot account_balance (จะทำงานเฉพาะ backtest/forward_test) -----
            self._snapshot_account_balance(
                timestamp_ms=timestamp_ms,
                current_price=price,
                notes=f"SELL @ {price}",
            )

        # เก็บเฉพาะ positions ที่ยังไม่ถึงเป้าหมาย
        self.positions = remaining_positions

    # ------------------------------------------------------------------
    # Hedge logic (โครง)
    # ------------------------------------------------------------------

    def _process_hedge(self, timestamp_ms: int, price: float) -> None:
        """
        ใส่ rule สำหรับ hedge ที่ระดับต่ำกว่ากริดล่างสุด
        ตรงนี้เป็นโครงไว้ให้ – detailed rule ค่อยเติม
        """
        if not self.grid_prices:
            return

        lowest = min(self.grid_prices)

        # example condition: price ต่ำกว่า lowest grid - ATR(approx)
        # ตอนนี้ยังไม่คำนวณ ATR ต่อบาร์ที่นี่ เพื่อความง่าย เอา logic เดิมมาใส่ทีหลังได้
        if price < lowest:
            # TODO: เติม rule เก่า เช่น เปิด hedge 50% ของ spot qty ที่ถืออยู่ เป็นต้น
            pass

        # TODO: logic ปิด hedge เช่น price กลับขึ้นเหนือ entry + ATR ก็ปิด ฯลฯ
        # self._io_close_hedge(...)

    def _calc_unrealized_pnl(self, current_price: float) -> float:
        """
        รวม unrealized PnL ของ spot positions ทั้งหมด ณ ราคา current_price
        """
        pnl = 0.0
        for p in self.positions:
            pnl += (current_price - p.entry_price) * p.qty
        return float(pnl)

    def _calc_equity(self, current_price: float) -> float:
        """
        Equity = เงินสด (available + reserve) + มูลค่าตลาดของ position ทั้งหมด
        """
        cash = float(self.available_capital + self.reserve_capital)
        pos_value = 0.0
        for p in self.positions:
            pos_value += p.qty * current_price
        return cash + pos_value

    def _snapshot_account_balance(
        self,
        timestamp_ms: int,
        current_price: float,
        notes: str = "",
    ) -> None:
        """
        สร้าง snapshot ลง table account_balance
        - ใช้เฉพาะ backtest/forward_test (กันไม่ให้ spam ตอน live)
        """
        if self.mode not in ("backtest", "forward_test"):
            return

        if not hasattr(self, "acc_balance_db") or self.acc_balance_db is None:
            return

        dt = datetime.fromtimestamp(timestamp_ms / 1000)
        record_date = dt.strftime("%Y-%m-%d")
        record_time = dt.strftime("%H:%M:%S")

        equity       = self._calc_equity(current_price)
        unrealized   = self._calc_unrealized_pnl(current_price)
        realized_pnl = float(self.realized_grid_profit)
        # backtest: net_flow_usdt = 0 (ไม่มีฝากถอน), fees_usdt = 0 (ถ้ายังไม่ได้คิด fee)
        data = {
            "record_date": record_date,
            "record_time": record_time,
            "start_balance_usdt": round(equity, 6),
            "net_flow_usdt": 0.0,
            "realized_pnl_usdt": round(realized_pnl, 6),
            "unrealized_pnl_usdt": round(unrealized, 6),
            "fees_usdt": 0.0,
            "end_balance_usdt": round(equity, 6),
            "notes": notes,
        }

        try:
            self.acc_balance_db.insert_balance(data)
        except Exception as e:
            self.logger.log(f"[AccountBalance] insert_balance error: {e}", level="ERROR")