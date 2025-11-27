# base_strategy.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np

from grid_bot.interface.io_interface import IGridIO
from grid_bot.database.grid_states import GridState
from grid_bot.database.ohlcv_data import OhlcvData
from grid_bot.database.spot_orders import SpotOrders
from grid_bot.database.future_orders import FuturesOrders
from grid_bot.database.account_balance import AccountBalance
from grid_bot.database.logger import Logger

from grid_bot.strategy.atr_calculator import ATRCalculator as atr_calc
from grid_bot.datas.position import Position
import grid_bot.utils.util as util


class BaseGridStrategy(IGridIO):
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
        reserve_ratio: float,
        mode: str,
        logger: Optional[Logger] = None,
    ) -> None:
        self.symbol = symbol
        self.symbol_future = symbol_future
        self.mode = mode

        # Money
        self.initial_capital = float(initial_capital)
        self.reserve_ratio = float(reserve_ratio)
        self.total_capital = float(initial_capital)
        self.reserve_capital = self.total_capital * self.reserve_ratio
        self.futures_available_margin = self.total_capital * self.reserve_ratio  # assume half for futures margin
        self.available_capital = self.total_capital - (self.reserve_capital + self.futures_available_margin)

        # Grid config
        self.grid_levels = int(grid_levels)
        self.atr_multiplier = float(atr_multiplier)
        self.spot_fee_rate: float = 0.001
        self.grid_prices: List[float] = []
        self.grid_filled: Dict[float, bool] = {}  # grid_price -> bool
        self.grid_group_id: Optional[str] = None
        self.grid_spacing: float = 0.0  # ระยะห่าง grid ปัจจุบัน (ใช้ทั้ง init+recalc)

        # >>> NEW: flag สำหรับ recenter ที่รอ hedge ทำงานก่อน <<<
        self.pending_recenter: Optional[dict] = None

        # tuning parameter สำหรับ recalc
        self.vol_up_ratio: float = 1.5  # ATR14 > ATR28 * 1.5 → ถือว่าผันผวนสูง
        self.vol_down_ratio: float = 0.7  # ATR14 < ATR28 * 0.7 → ถือว่านิ่งลง
        self.drift_k: float = 2.5  # price เลยกรอบเดิม k ช่อง → recenter ใหม่

        # state runtime
        self.positions: List[Position] = []
        self.realized_grid_profit: float = 0.0
        self.prev_close: Optional[float] = None

        # ==== HEDGE CONFIG (เน้นรักษาเงินต้น) ====
        self.hedge_size_ratio: float = 0.5  # hedge 50% ของ net spot เป็นเป้า max
        self.hedge_leverage: int = 2  # leverage ฝั่ง futures (เอาไปใช้ใน I/O layer)
        self.hedge_open_k_atr: float = 0.5  # เปิด hedge เพิ่มเมื่อหลุด lowest - 0.5*ATR
        self.hedge_tp_ratio: float = 0.05  # TP hedge เมื่อกำไร hedge ~ 5% ของ spot unrealized loss
        self.hedge_sl_ratio: float = 0.1  # SL hedge เมื่อขาดทุน ~ 10% ของ spot unrealized loss
        self.min_hedge_notional: float = 5.0  # notional ขั้นต่ำของ hedge (กัน dust)
        self.hedge_max_loss_ratio: float = 1.0  # max hedge loss relative to |spot loss|
        self.hedge_min_hold_ms: int = 5 * 60 * 1000  # hold time before reversal cut

        # EMA ที่ใช้ filter
        self.ema_fast_period: int = 14
        self.ema_mid_period: int = 50
        self.ema_slow_period: int = 200

        # เก็บสถานะ hedge ปัจจุบัน (short futures)
        # {"qty": float, "entry": float, "timestamp": int}
        self.hedge_position: Optional[dict] = None

        # symbol ฝั่ง futures (ถ้าไม่เหมือน spot ค่อย override ใน subclass)
        self.futures_symbol: str = self.symbol_future

        # DB
        self.grid_db = GridState()
        self.ohlcv_db = OhlcvData()
        self.spot_orders_db = SpotOrders()
        self.futures_db = FuturesOrders()
        self.acc_balance_db = AccountBalance()

        self.logger = logger or Logger()
        self.logger.log(
            f"[BaseGridStrategy] Init mode={mode}, symbol={symbol}, capital={self.total_capital}, reserve capital= {self.reserve_capital}, intial margin={self.futures_available_margin}, grid_levels={grid_levels}, atr_multiplier={atr_multiplier}, reserve_ratio={reserve_ratio}",
            level="INFO",
        )

    # ------------------------------------------------------------------
    # Common Logic
    # ------------------------------------------------------------------
    def _calc_atr_ema_from_df(self, df: pd.DataFrame, atr_periods: Tuple[int, ...] = (14, 28), ema_periods: Tuple[int, ...] = (14, 28, 50, 100, 200)) -> Dict[str, float]:
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
        tr_series = atr_calc._calc_tr_series(df)
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

    def define_spacing_size(self, atr_period: int, history: pd.DataFrame) -> float:
        """
        Legacy helper for spacing sizing using TR/ATR on a High/Low/Close dataframe.
        """
        if history is None or history.empty:
            return 0.0

        df = history.copy()
        # Normalize column names if capitalized
        high = df["High"] if "High" in df else df.get("high")
        low = df["Low"] if "Low" in df else df.get("low")
        close = df["Close"] if "Close" in df else df.get("close")
        tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)

        atr = tr.rolling(atr_period).mean()
        last_tr = float(tr.iloc[-1])
        last_atr = float(atr.iloc[-1]) if not pd.isna(atr.iloc[-1]) else float("nan")
        multiplier = 2.0 if last_tr > last_atr else 1.0

        try:
            self.prev_close = float(close.iloc[-1])
        except Exception:
            pass

        return float(last_tr * multiplier)

    def _calc_atr_ema(self, timestamp: float, open: float, close: float, high: float, low: float, volume: float, hist_df: Optional[pd.DataFrame] = None) -> int:
        """
        Common Engine:
        - TR
        - ATR(14, 28)
        - EMA(14, 28, 50, 100, 200)
        Insert into ohlcv_db

        แหล่งข้อมูล:
        - ถ้า hist_df ไม่ว่าง → ใช้ hist_df (จากไฟล์ backtest) + append แท่งปัจจุบัน
        - ถ้า hist_df ว่าง → ใช้ history จาก DB แล้วต่อท้ายแท่งปัจจุบัน
        """

        # ------------------------------------------------------------------
        # 1) Prepare DataFrame source
        # ------------------------------------------------------------------
        if hist_df is not None and not hist_df.empty:
            # add hist_df from backtest + append the current row with timestamp, open, high, low, close, volume
            hist = hist_df.rename(
                columns={
                    "Open": "open",
                    "High": "high",
                    "Low": "low",
                    "Close": "close",
                    "Volume": "volume",
                }
            ).copy()

            # ensure numeric
            for c in ["open", "high", "low", "close", "volume"]:
                if c in hist.columns:
                    hist[c] = hist[c].astype(float)

            current_row = pd.DataFrame([{"open": float(open), "high": float(high), "low": float(low), "close": float(close), "volume": float(volume)}], index=[timestamp])  # ใช้ timestamp เป็น index

            df_src = pd.concat([hist, current_row], axis=0)
        else:
            # เคส live หรือไม่มี hist_df → ใช้ DB แทน
            hist = self.ohlcv_db.get_recent_ohlcv(self.symbol, 200)

            current_row = pd.DataFrame([{"time": timestamp, "open": float(open), "high": float(high), "low": float(low), "close": float(close), "volume": float(volume)}]).set_index("time")

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

        tr = float(vals["tr"])
        atr_14 = float(vals["atr_14"])
        atr_28 = float(vals["atr_28"])
        ema_14 = float(vals["ema_14"])
        ema_28 = float(vals["ema_28"])
        ema_50 = float(vals["ema_50"])
        ema_100 = float(vals["ema_100"])
        ema_200 = float(vals["ema_200"])

        # ------------------------------------------------------------------
        # 3) INSERT ลง DB (1 row ของแท่งปัจจุบัน)
        # ------------------------------------------------------------------
        rowcount = self.ohlcv_db.insert_ohlcv_data(
            symbol=self.symbol,
            timestamp=int(timestamp),
            open=float(open),
            high=float(high),
            low=float(low),
            close=float(close),
            volume=float(volume),
            tr=float(tr),
            atr_14=float(atr_14),
            atr_28=float(atr_28),
            ema_14=float(ema_14),
            ema_28=float(ema_28),
            ema_50=float(ema_50),
            ema_100=float(ema_100),
            ema_200=float(ema_200),
        )

        return rowcount

    def _maybe_recenter_grid(self, timestamp_ms: int, price: float, atr_14: float, atr_28: float) -> None:
        """
        Decision layer for hard recenter.
        - check grid existence
        - drift / fill ratio
        - hedge PnL guard (skip if hedge loss)
        """
        if not self.grid_prices:
            return

        spacing = self.grid_spacing
        if spacing <= 0 and len(self.grid_prices) >= 2:
            spacing = float(self.grid_prices[1] - self.grid_prices[0])
        if spacing <= 0 and atr_14 > 0:
            spacing = atr_14 * self.atr_multiplier
        if spacing <= 0:
            return

        lowest = min(self.grid_prices)
        highest = max(self.grid_prices)

        # state of usage
        filled_levels = sum(1 for p in self.grid_prices if self.grid_filled.get(p, False))
        fill_ratio = filled_levels / len(self.grid_prices) if self.grid_prices else 0.0

        need_recenter = False
        if price > highest + spacing * self.drift_k or price < lowest - spacing * self.drift_k:
            need_recenter = True
        elif fill_ratio > 0.7:
            need_recenter = True

        if not need_recenter:
            return

        # ดึง row + ตรวจ trend
        last = self.ohlcv_db.get_recent_ohlcv(self.symbol, 1)
        if last is None or last.empty:
            return

        row = last.iloc[-1].to_dict()
        trend = self._get_trend_direction(row, price)

        # ===============================
        # 1) DOWNTREND:
        #    - cancel buy ที่ยังไม่ fill
        #    - ขาย spot ครึ่งหนึ่ง + เปิด hedge ให้ cover loss
        #    - ทำ "pending recenter" ไว้ → ให้ hedge จัดการต่อ
        # ===============================
        if trend == "down":
            self._recenter_downtrend(timestamp_ms, price, atr_14, atr_28, row)

            # mark ว่ามี recenter รออยู่ ให้ hedge เป็นคน trigger ทีหลัง
            self.pending_recenter = {
                "initiated_at": timestamp_ms,
                "reason": "DOWN_TREND",
            }
            self.logger.log(
                f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - [GRID] recenter DOWN pending (wait hedge PnL >= 0)",
                level="INFO",
            )
            return

        # ===============================
        # 2) UPTREND:
        #    - ไม่ hedge ใหม่
        #    - ขายเฉพาะ spot ที่กำไร
        #    - ปิด grid เก่า + เปิด lower grid ใหม่ทันที
        # ===============================
        if trend == "up":
            self._recenter_uptrend(timestamp_ms, price, atr_14, atr_28)
            # path นี้ recenter เสร็จแล้วในตัวเอง ไม่ต้องเรียก _do_full_recenter
            return

        # ===============================
        # 3) SIDEWAYS / FALLBACK:
        #    ถ้าไม่ได้ชัดว่า up/down → ใช้ full recenter ปกติ
        #    พร้อม hedge guard: ถ้ามี hedge แล้วกำลังขาดทุนจะไม่ recenter
        # ===============================
        if self.hedge_position:
            h = self.hedge_position
            hedge_pnl = (float(h["entry"]) - float(price)) * float(h["qty"])
            if hedge_pnl < 0:
                self.logger.log(f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - [GRID] skip recenter due hedge loss (pnl={hedge_pnl:.4f})", level="INFO")
                return

        self._do_full_recenter(timestamp_ms=timestamp_ms, price=price, atr_14=atr_14, atr_28=atr_28)

    def _recalc_spacing_if_needed(self, atr_14: float, atr_28: float, curr_spacing: float) -> float:
        """
        Soft adjust spacing logic using ATR regime.
        - ใช้ ATR14 เทียบกับ ATR28 เพื่อตัดสินใจว่าจะขยาย/หด grid หรือไม่
        - ถ้าไม่เปลี่ยนถือว่าใช้ spacing เดิม
        """
        if atr_14 <= 0 or atr_28 <= 0 or not self.grid_prices:
            return curr_spacing

        # old_spacing: ใช้อันที่เคยเซ็ตไว้ ถ้าไม่มีลองคำนวณจาก grid จริง
        old_spacing = curr_spacing
        if old_spacing <= 0 and len(self.grid_prices) >= 2:
            old_spacing = float(self.grid_prices[1] - self.grid_prices[0])

        if old_spacing <= 0:
            # fallback ถ้ายังไม่มีอะไรเลย
            old_spacing = atr_14 * self.atr_multiplier

        new_spacing = 0.0
        # volatility regime
        if atr_14 > atr_28 * self.vol_up_ratio:
            # ตลาดผันผวนมาก → ขยายระยะห่าง grid
            new_spacing = atr_14 * self.atr_multiplier * 2.0
        elif atr_14 < atr_28 * self.vol_down_ratio:
            # ตลาดสงบ → หด grid ลง
            new_spacing = atr_14 * self.atr_multiplier * 1.0

        if new_spacing <= 0:
            return old_spacing
        else:
            return new_spacing

    def _init_lower_grid(self, timestamp_ms: int, base_price: float, atr: float, spacing_override: Optional[float] = None) -> None:
        """
        Create LOWER-only grid (the requirement USDT-only buy low and sell high at the base price)
        """
        spacing = spacing_override if spacing_override and spacing_override > 0 else None
        if spacing is None:
            if atr <= 0:
                spacing = base_price * 0.03  # fallback 3%, If the ATR value is less than 0
            else:
                spacing = atr * self.atr_multiplier

        # เก็บ spacing ปัจจุบันไว้ใช้ตอน recalc
        self.grid_spacing = float(spacing)

        # คำนวณราคากริดด้านล่าง
        self.grid_prices = [round(base_price - spacing * (i + 1), 4) for i in range(self.grid_levels)]

        self.grid_prices = sorted(self.grid_prices)
        self.grid_group_id = util.generate_order_id("INIT")
        self.grid_filled = {p: False for p in self.grid_prices}

        now_date = datetime.now().strftime("%Y-%m-%d")
        now_time = datetime.now().strftime("%H:%M:%S")
        now_dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for price in self.grid_prices:
            item = {
                "symbol": self.symbol,
                "grid_price": price,
                "use_status": "Y",
                "group_id": self.grid_group_id,
                "base_price": float(base_price),
                "spacing": float(spacing),
                "date": now_date,
                "time": now_time,
                "create_date": now_dt,
                "status": "open",
            }
            self.grid_db.save_state(item)

        self.logger.log(f"Date {util.timemstamp_ms_to_date(timestamp_ms)} - Grid initialized (LOWER only) base={base_price}, group={self.grid_group_id}, prices={self.grid_prices}", level="INFO")

    def _compute_recenter_spacing(self, price: float, atr_14: float, atr_28: float, prior_spacing: float = 0.0) -> float:
        """
        Hard recenter spacing logic using ATR regime.
        """
        spacing = 0.0
        if atr_14 > 0:
            base = atr_14 * self.atr_multiplier
            if atr_28 > 0:
                ratio = atr_14 / atr_28
                if ratio >= self.vol_up_ratio:
                    spacing = base * 1.3
                elif ratio <= self.vol_down_ratio:
                    spacing = base * 0.8
                else:
                    spacing = base
            else:
                spacing = base
        else:
            spacing = prior_spacing if prior_spacing and prior_spacing > 0 else 0.0

        if spacing <= 0:
            spacing = price * 0.03

        return float(spacing)

    def _recenter_downtrend(self, timestamp_ms: int, price: float, atr_14: float, atr_28: float, row: dict) -> None:
        """
        Downtrend recenter flow:

        1) ยกเลิก BUY orders ที่ยังไม่ถูก fill ทั้งหมดใน grid group ปัจจุบัน
        2) รวม spot ทั้งหมด แล้วขายออก "ครึ่งหนึ่ง" (reduce exposure)
           - ใช้ _io_place_spot_sell เดิม แต่สร้าง Position ชั่วคราวเพื่อ partial close
        3) หลังขายครึ่งหนึ่ง → คำนวณ hedge ให้ cover net spot ที่เหลือ (target_ratio ~ 1.0)
        4) ไม่ทำ full recenter ทันที แต่ set self.pending_recenter
           ให้รอ _manage_hedge_exit() เรียก _do_full_recenter เมื่อ hedge PnL >= 0
        """

        # 1) ปิด BUY orders ที่ยังไม่ถูก fill ทั้งหมดใน grid ปัจจุบัน
        if self.grid_group_id:
            try:
                closed = self.spot_orders_db.close_open_orders_by_group(symbol=self.symbol, grid_id=self.grid_group_id, reason="RECENTER_DOWN_TREND_CANCEL_BUYS")
                self.logger.log(f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - " f"[GRID] recenter_downtrend: cancel open BUY orders count={closed}", level="INFO")
            except Exception as e:
                self.logger.log(f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - " f"[GRID] recenter_downtrend: close_open_orders_by_group error: {e}", level="ERROR")

        # 2) รวม spot qty ทั้งหมด
        total_qty = sum(p.qty for p in self.positions)
        if total_qty <= 0:
            # ไม่มี spot ให้จัดการ → แค่ mark pending_recenter ไว้ให้ hedge ทำงานต่อ
            self.logger.log(f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - " "[GRID] recenter_downtrend: no spot positions, skip SL half.", level="INFO")
            return

        target_sl_qty = total_qty * 0.5
        qty_to_sl = target_sl_qty

        # ขายจาก position ที่ entry สูงก่อน (เสี่ยงสุด)
        positions_sorted = sorted(self.positions, key=lambda p: p.entry_price, reverse=True)
        new_positions: List[Position] = []
        is_paper = self.mode in ("backtest", "forward_test")

        for p in positions_sorted:
            if qty_to_sl <= 0:
                # ไม่ต้องขายเพิ่มแล้ว เก็บ position ไว้ทั้งก้อน
                new_positions.append(p)
                continue

            sell_qty = min(p.qty, qty_to_sl)

            # --- ใช้ _io_place_spot_sell เดิม แต่ทำ partial โดยสร้าง Position ชั่วคราว ---
            sell_pos = Position(
                symbol=p.symbol,
                side=p.side,
                entry_price=p.entry_price,
                qty=sell_qty,
                grid_price=p.grid_price,
                target_price=p.target_price,
                opened_at=p.opened_at,
                group_id=p.group_id,
                hedged=p.hedged,
                meta=p.meta,
            )

            try:
                self._io_place_spot_sell(timestamp_ms=timestamp_ms, position=sell_pos, sell_price=price)
            except Exception as e:
                self.logger.log(
                    f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - " f"[RECENTER_DOWN] spot partial sell error entry={p.entry_price}: {e}",
                    level="ERROR",
                )
                # ถ้าขายไม่สำเร็จ ยังเก็บ position เดิมไว้
                new_positions.append(p)
                continue

            if is_paper:
                notional = price * sell_qty
                pnl = (price - p.entry_price) * sell_qty
                self.available_capital += notional
                self.realized_grid_profit += pnl

                self.logger.log(
                    f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - "
                    f"[RECENTER_DOWN][PAPER] partial SELL qty={sell_qty:.4f} @ {price:.4f}, "
                    f"entry={p.entry_price:.4f}, pnl={pnl:.4f}, "
                    f"total_realized={self.realized_grid_profit:.4f}",
                    level="INFO",
                )

            qty_to_sl -= sell_qty

            # ถ้าเหลือบางส่วนของ position เดิม → เก็บกลับเข้า new_positions
            remaining_qty = p.qty - sell_qty
            if remaining_qty > 0:
                new_positions.append(
                    Position(
                        symbol=p.symbol,
                        side=p.side,
                        entry_price=p.entry_price,
                        qty=remaining_qty,
                        grid_price=p.grid_price,
                        target_price=p.target_price,
                        opened_at=p.opened_at,
                        group_id=p.group_id,
                        hedged=p.hedged,
                        meta=p.meta,
                    )
                )

        self.positions = new_positions

        # 3) หลังจากขายครึ่งหนึ่ง → คำนวณ hedge size ให้ cover net spot ที่เหลือ
        remaining_qty = sum(p.qty for p in self.positions)
        if remaining_qty <= 0:
            self.logger.log(
                f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - " "[RECENTER_DOWN] no remaining spot after SL half, skip hedge scale-in.",
                level="INFO",
            )
            return

        try:
            self._ensure_hedge_ratio(
                timestamp_ms=timestamp_ms,
                target_ratio=1.0,  # hedge ประมาณ 100% ของ net spot ที่เหลือ
                price=price,
                net_spot_qty=remaining_qty,
                reason="RECENTER_DOWN_TREND_HEDGE",
            )
        except Exception as e:
            self.logger.log(
                f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - " f"[RECENTER_DOWN] ensure_hedge_ratio error: {e}",
                level="ERROR",
            )

        # (option) snapshot account balance ใน backtest
        self._snapshot_account_balance(
            timestamp_ms=timestamp_ms,
            current_price=price,
            side="RECENTER_DOWN",
            notes="recenter_downtrend: SL half + hedge scale-in",
        )

    def _recenter_uptrend(self, timestamp_ms: int, price: float, atr_14: float, atr_28: float) -> None:
        """
        UPTREND recenter flow:

        0) ไม่เปิด hedge ใหม่
        1) ถ้ามี hedge เดิมและกำไร/ไม่ขาดทุน → ปิดก่อน
        2) ขาย spot ที่มีกำไรทั้งหมด (lock profit)
        3) deactivate grid เก่า + cancel open orders ทั้งหมดของ group เดิม
        4) reset in-memory grid แล้วสร้าง lower-only grid ใหม่ตาม ATR
        """

        # 0) ไม่เปิด hedge ใหม่ใน path นี้

        # ถ้ามี hedge position ค้างอยู่ และกำไร/ไม่ขาดทุน -> ปิดทิ้งไปก่อน
        if self.hedge_position:
            h = self.hedge_position
            hedge_pnl = (float(h["entry"]) - price) * float(h["qty"])
            if hedge_pnl >= 0:
                self.logger.log(
                    f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - " f"[RECENTER_UP] close existing hedge with pnl={hedge_pnl:.4f}",
                    level="INFO",
                )
                self._close_hedge(
                    timestamp_ms=timestamp_ms,
                    price=price,
                    reason="UPTREND_RECENTER_CLOSE_HEDGE",
                )

        # 1) ขาย spot ที่มีกำไรทั้งหมด
        is_paper = self.mode in ("backtest", "forward_test")
        new_positions: List[Position] = []

        for p in self.positions:
            unreal = (price - p.entry_price) * p.qty
            if unreal > 0:
                # ขายเอากำไร
                try:
                    self._io_place_spot_sell(
                        timestamp_ms=timestamp_ms,
                        position=p,
                        sell_price=price,
                    )
                except Exception as e:
                    self.logger.log(
                        f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - " f"[RECENTER_UP] spot sell error entry={p.entry_price}: {e}",
                        level="ERROR",
                    )
                    # ถ้าขายไม่สำเร็จ → ยังเก็บ position ไว้
                    new_positions.append(p)
                    continue

                if is_paper:
                    notional = price * p.qty
                    pnl = unreal
                    self.available_capital += notional
                    self.realized_grid_profit += pnl

                    self.logger.log(
                        f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - "
                        f"[RECENTER_UP][PAPER] SELL profitable pos entry={p.entry_price:.4f}, "
                        f"qty={p.qty:.4f}, pnl={pnl:.4f}, total_realized={self.realized_grid_profit:.4f}",
                        level="INFO",
                    )
            else:
                new_positions.append(p)

        self.positions = new_positions

        # 2) Deactivate grid เก่า + close open orders ทั้งหมดของ group เดิม
        old_group = self.grid_group_id
        if old_group:
            try:
                deact = self.grid_db.deactivate_group(
                    symbol=self.symbol,
                    group_id=old_group,
                    reason="RECENTER_UP",
                )
                self.logger.log(
                    f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - " f"[GRID] recenter_uptrend: deactivate_group group={old_group}, rows={deact}",
                    level="INFO",
                )
            except Exception as e:
                self.logger.log(
                    f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - " f"[GRID] recenter_uptrend deactivate_group error: {e}",
                    level="ERROR",
                )

            try:
                closed_spot = self.spot_orders_db.close_open_orders_by_group(
                    symbol=self.symbol,
                    grid_id=old_group,
                    reason="RECENTER_UP",
                )
                self.logger.log(
                    f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - " f"[SPOT] recenter_uptrend: cancel open orders group={old_group}, count={closed_spot}",
                    level="INFO",
                )
            except Exception as e:
                self.logger.log(
                    f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - " f"[SPOT] recenter_uptrend close_open_orders_by_group error: {e}",
                    level="ERROR",
                )

            try:
                closed_fut = self.futures_db.close_open_orders_by_group(
                    symbol=self.symbol_future,
                    reason="RECENTER_UP",
                )
                self.logger.log(
                    f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - " f"[FUTURES] recenter_uptrend: close_open_orders_by_group symbol={self.symbol_future}, count={closed_fut}",
                    level="INFO",
                )
            except Exception as e:
                self.logger.log(
                    f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - " f"[FUTURES] recenter_uptrend close_open_orders_by_group error: {e}",
                    level="ERROR",
                )

        # 3) Reset in-memory grid แต่ไม่ยุ่งกับ spot ขาดทุนที่เหลือ
        self.grid_prices = []
        self.grid_filled = {}
        self.grid_group_id = None
        self.grid_spacing = 0.0
        # self.hedge_position น่าจะถูกปิดไปแล้วด้านบน ถ้า pnl >= 0

        # 4) สร้าง lower-only grid ใหม่ตาม ATR เหมือนเดิม
        new_spacing = self._compute_recenter_spacing(
            price=price,
            atr_14=atr_14,
            atr_28=atr_28,
            prior_spacing=self.grid_spacing,
        )
        self._init_lower_grid(
            timestamp_ms=timestamp_ms,
            base_price=price,
            atr=atr_14,
            spacing_override=new_spacing,
        )

    def _do_full_recenter(self, timestamp_ms: int, price: float, atr_14: float, atr_28: float) -> None:
        """
        Execute full recenter pipeline:
        - close hedge if non-negative PnL
        - rebalance spot using hedge profit
        - liquidate remaining spot to free USDT
        - deactivate old grid and open orders
        - build new lower-only grid using ATR regime spacing
        """
        old_group = self.grid_group_id
        prior_spacing = self.grid_spacing

        # -------- Hedge management --------
        if self.hedge_position:
            h = self.hedge_position
            hedge_qty = float(h["qty"])
            hedge_entry = float(h["entry"])
            hedge_pnl = (hedge_entry - price) * hedge_qty  # short

            if hedge_pnl < 0:
                # safety guard already checked, but double-check
                self.logger.log(f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - [HEDGE] skip recenter due hedge loss: pnl={hedge_pnl:.4f}", level="INFO")
                return

            self._close_hedge(timestamp_ms=timestamp_ms, price=price, reason="RECENTER")

            # use hedge profit to rebalance spot
            try:
                self._rebalance_spot_after_hedge(timestamp_ms=timestamp_ms, hedge_pnl=hedge_pnl, price=price)
            except Exception as e:
                self.logger.log(f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - [HEDGE] rebalance spot error: {e}", level="ERROR")

        # -------- Force close remaining spot --------
        remaining_positions: List[Position] = []
        is_paper_mode = self.mode in ("backtest", "forward_test")
        for pos in self.positions:
            try:
                self._io_place_spot_sell(timestamp_ms=timestamp_ms, position=pos, sell_price=price)
                if is_paper_mode:
                    notional = price * pos.qty
                    pnl = (price - pos.entry_price) * pos.qty
                    self.available_capital += notional
                    self.realized_grid_profit += pnl
            except Exception as e:
                self.logger.log(f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - [RECENTER] spot sell error entry={pos.entry_price}: {e}", level="ERROR")
                remaining_positions.append(pos)

        self.positions = remaining_positions if self.mode == "live" else []

        # -------- Deactivate old grid + orders --------
        if old_group:
            try:
                self.grid_db.deactivate_group(symbol=self.symbol, group_id=old_group, reason="RECENTER")
            except Exception as e:
                self.logger.log(f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - [GRID] deactivate_group error: {e}", level="ERROR")
            try:
                self.spot_orders_db.close_open_orders_by_group(symbol=self.symbol, grid_id=old_group, reason="RECENTER")
            except Exception as e:
                self.logger.log(f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - [SPOT] close_open_orders_by_group error: {e}", level="ERROR")

        try:
            self.futures_db.close_open_orders_by_group(symbol=self.symbol_future, reason="RECENTER")
        except Exception as e:
            self.logger.log(f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - [FUTURES] close_open_orders_by_group error: {e}", level="ERROR")

        # reset in-memory grid/hedge
        self.grid_prices = []
        self.grid_filled = {}
        self.grid_group_id = None
        self.grid_spacing = 0.0
        self.hedge_position = None

        # -------- Build new grid --------
        new_spacing = self._compute_recenter_spacing(price=price, atr_14=atr_14, atr_28=atr_28, prior_spacing=prior_spacing)
        self._init_lower_grid(timestamp_ms=timestamp_ms, base_price=price, atr=atr_14, spacing_override=new_spacing)

        self.logger.log(
            f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - [GRID] recentered → new group={self.grid_group_id}, spacing={new_spacing:.6f}, prices={self.grid_prices}",
            level="INFO",
        )

    def on_candle(self, timestamp_ms: int, open_price: float, high: float, low: float, close: float, volume: float, hist_df: Optional[pd.DataFrame] = None) -> Optional[dict]:
        """
        Thin wrapper for candle ingestion to match tests/helpers; delegates to on_bar and
        returns the latest indicator row if available.
        """
        self.on_bar(timestamp_ms, open_price, high, low, close, volume, hist_df=hist_df)
        if not hasattr(self, "ohlcv_db") or self.ohlcv_db is None:
            return None
        last = self.ohlcv_db.get_recent_ohlcv(self.symbol, 1)
        if last is None or last.empty:
            return None
        return last.iloc[-1].to_dict()

    def on_bar(self, timestamp_ms: int, open_price: float, high: float, low: float, close: float, volume: float, hist_df: Optional[pd.DataFrame] = None) -> None:

        # ===============================================================
        # 1) Update OHLCV + ATR/EMA → INSERT into DB
        # ===============================================================
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

        # ===============================================================
        # 2) Load latest indicator row
        # ===============================================================
        last = self.ohlcv_db.get_recent_ohlcv(self.symbol, 1)
        if last is None or last.empty:
            return

        row = last.iloc[-1].to_dict()

        atr_14 = float(row.get("atr_14", 0.0) or 0.0)
        atr_28 = float(row.get("atr_28", 0.0) or 0.0)

        # ===============================================================
        # 3) Load grid state (from DB → memory)
        # ===============================================================
        if not self.grid_prices:
            rows = self.grid_db.load_state_with_use_flgs(self.symbol, "Y")
            if rows:
                self.grid_prices = [float(r["grid_price"]) for r in rows]
                self.grid_group_id = rows[0]["group_id"]

                # grid_state table has no per-level filled flag; default to open=False until buys happen
                self.grid_filled = {float(r["grid_price"]): False for r in rows}

                if len(self.grid_prices) >= 2:
                    self.grid_spacing = float(self.grid_prices[1] - self.grid_prices[0])

        # ===============================================================
        # 4) Init grid (first run) OR Recalc grid
        # ===============================================================
        if not self.grid_prices:
            self._init_lower_grid(timestamp_ms=timestamp_ms, base_price=price, atr=atr_14)
        else:

            old_spacing = self.grid_spacing
            new_spacing = self._recalc_spacing_if_needed(atr_14=atr_14, atr_28=atr_28, curr_spacing=old_spacing)

            # ต้องต่างกันมากกว่า 20% ถึงจะปรับ น้อยกว่านั้นจะไม่ปรับ เพื่อลด churn
            if old_spacing > 0 and abs(new_spacing - old_spacing) / old_spacing > 0.2:
                self.logger.log(
                    f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - [GRID] spacing adjusted from {old_spacing:.4f} to {new_spacing:.4f} " f"(ATR14={atr_14:.4f}, ATR28={atr_28:.4f})", level="INFO"
                )
                self.grid_spacing = new_spacing

            # ตรวจสอบ drift/fill → recenter แบบเต็มรูปแบบ
            self._maybe_recenter_grid(timestamp_ms=timestamp_ms, price=price, atr_14=atr_14, atr_28=atr_28)

        # ===============================================================
        # 5) Process BUY / SELL
        # ===============================================================
        self._process_buy_grid(timestamp_ms, price)
        self._process_sell_grid(timestamp_ms, price)

        # ===============================================================
        # 6) Hedge now requires ATR/EMA row → pass row dict
        # ===============================================================
        self._process_hedge(timestamp_ms, price, row)

    # ------------------------------------------------------------------
    # BUY logic
    # ------------------------------------------------------------------
    def _process_buy_grid(self, timestamp_ms: int, price: float) -> None:
        """
        ถ้าราคาลงมาชน grid และมีทุน → เปิด position
        """
        # refresh available from DB (spot)
        try:
            self._io_refresh_balances()
        except Exception as e:
            self.logger.log(f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - [BAL] refresh spot available error: {e}", level="ERROR")

        # นับจำนวน grid ที่ยังไม่ถูกซื้อ
        remaining_slots = sum(1 for p in self.grid_prices if not self.grid_filled.get(p, False))
        if remaining_slots <= 0:
            return

        # calculate us order_size_usdt แบบ dynamic จาก remaining_slots
        order_size_usdt = self._compute_dynamic_order_size(remaining_slots)

        for level_price in self.grid_prices:
            filled = self.grid_filled.get(level_price, False)
            if price <= level_price and not filled:
                qty = round(order_size_usdt / level_price, 6)
                notional = level_price * qty
                fee = notional * self.spot_fee_rate
                total_cost = notional + fee

                if self.available_capital < total_cost:
                    self.logger.log(
                        f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - Skip BUY grid@{level_price}: insufficient capital " f"(available={self.available_capital:.4f}, required={total_cost:.4f})",
                        level="INFO",
                    )
                    continue

                order_info = self._io_place_spot_buy(timestamp_ms=timestamp_ms, price=level_price, qty=qty, grid_id=self.grid_group_id)
                self.available_capital = max(0.0, self.available_capital - total_cost)

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
                    group_id=self.grid_group_id,
                    meta={"order": order_info},
                )

                self.positions.append(pos)
                self.grid_filled[level_price] = True
                self.logger.log(
                    f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - Grid BUY filled @ {level_price} qty={qty}, target={target}, notional={notional}, fee={fee}, remaining_cap={self.available_capital}",
                    level="INFO",
                )

                # Snapshot account_balance (It's support only in the backtest/forward_test mode.)
                self._snapshot_account_balance(timestamp_ms=timestamp_ms, current_price=price, side="BUY", notes=f"BUY @ {level_price}")

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
                self.available_capital += notional - fee
                self.realized_grid_profit += pnl

                self.logger.log(
                    f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - [PAPER] Grid SELL: entry={pos.entry_price}, "
                    f"target={pos.target_price}, sell={price}, "
                    f"qty={pos.qty}, pnl={pnl}, "
                    f"total_realized={self.realized_grid_profit}",
                    level="INFO",
                )
            else:
                # live → แค่บันทึกว่าได้สั่งขายแล้ว (ให้ไปดู fill จริงจาก exchange/DB)
                self.logger.log(
                    f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - [LIVE] Grid SELL order placed: entry={pos.entry_price}, "
                    f"target={pos.target_price}, sell={price}, "
                    f"qty={pos.qty}, est_pnl≈{pnl}",
                    level="INFO",
                )

            # ----- ปลดล็อก grid level นี้ ให้เปิด BUY ใหม่ได้ -----
            try:
                self.grid_filled[pos.grid_price] = False
            except Exception as e:
                self.logger.log(
                    f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - [GRID] grid_filled update error for price={pos.grid_price}: {e}",
                    level="ERROR",
                )

            # ----- snapshot account_balance (จะทำงานเฉพาะ backtest/forward_test) -----
            self._snapshot_account_balance(timestamp_ms=timestamp_ms, current_price=price, side="SELL", notes=f"SELL @ {price}")

        # เก็บเฉพาะ positions ที่ยังไม่ถึงเป้าหมาย
        self.positions = remaining_positions

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

    # ==================================================================
    #   HEDGE LOGIC (EMA + ZONE)
    # ==================================================================
    def _process_hedge(self, timestamp_ms: int, price: float, row: dict) -> None:
        """
        จัดการ hedge:
        - เริ่ม hedge ตั้งแต่ราคาเข้า Danger Zone (ระหว่าง L2 กับ L1) ถ้า EMA ยืนยัน downtrend
        - เพิ่ม hedge เมื่อหลุด lowest grid - k*ATR
        - ปิด hedge ตาม PnL + EMA reversal
        - ใช้กำไร hedge มาช่วยลด spot (รักษาเงินต้น)
        """

        # ถ้ายังไม่มีกลยุทธ์ grid / ไม่มี position spot → ไม่ hedge
        if not self.grid_prices or not self.positions:
            return

        # ATR & EMA จาก row ล่าสุด
        atr = float(row.get("atr_14", 0.0) or 0.0)
        ema_fast = float(row.get(f"ema_{self.ema_fast_period}", 0.0) or 0.0)
        ema_mid = float(row.get(f"ema_{self.ema_mid_period}", 0.0) or 0.0)
        ema_slow = float(row.get(f"ema_{self.ema_slow_period}", 0.0) or 0.0)

        if atr <= 0 or ema_fast == 0 or ema_mid == 0 or ema_slow == 0:
            return

        # net spot
        net_spot_qty = sum(p.qty for p in self.positions)
        if net_spot_qty <= 0:
            return

        avg_spot_cost = sum(p.entry_price * p.qty for p in self.positions) / net_spot_qty
        spot_unrealized = (price - avg_spot_cost) * net_spot_qty  # มักเป็นลบถ้าติดดอย

        grid_sorted = sorted(self.grid_prices)
        lowest = grid_sorted[0]
        second = grid_sorted[1] if len(grid_sorted) > 1 else lowest

        danger_start = second  # L2
        danger_end = lowest  # L1

        in_danger_zone = danger_end <= price <= danger_start

        # EMA filter
        downtrend_light = price < ema_fast < ema_mid
        downtrend_strong = price < ema_fast < ema_mid < ema_slow

        # ----------------- 1) เปิด / เพิ่ม hedge ใน Danger Zone -----------------
        if in_danger_zone and downtrend_light:
            # พยายามให้ hedge คิดเป็น 30% ของ net spot
            self._ensure_hedge_ratio(
                timestamp_ms=timestamp_ms,
                target_ratio=0.3,
                price=price,
                net_spot_qty=net_spot_qty,
                reason="DANGER_ZONE",
            )

        # ----------------- 2) เพิ่ม hedge เมื่อหลุด lowest grid - k*ATR -----------------
        price_break = price < (lowest - self.hedge_open_k_atr * atr)

        if price_break and downtrend_strong:
            # scale hedge ให้ขึ้นไปถึง 60% ของ net spot
            self._ensure_hedge_ratio(
                timestamp_ms=timestamp_ms,
                target_ratio=self.hedge_size_ratio,  # ใช้ 0.5–0.6 ตาม config
                price=price,
                net_spot_qty=net_spot_qty,
                reason="BREAK_LOWEST",
            )

        # ----------------- 3) จัดการปิด hedge (TP / SL / reversal) -----------------
        self._manage_hedge_exit(timestamp_ms, price, spot_unrealized, ema_fast, ema_mid)

    # ------------------------------------------------------------------
    def _ensure_hedge_ratio(self, timestamp_ms: Optional[int] = None, target_ratio: float = 0.0, price: float = 0.0, net_spot_qty: float = 0.0, reason: str = "") -> None:
        """
        ทำให้ขนาด hedge ปัจจุบันเข้าใกล้ target_ratio ของ net_spot_qty
        เช่น:
            - มี hedge เดิม 20% แต่ target 30% → เปิดเพิ่มอีก 10%
            - มี hedge อยู่แล้วเกิน target → ไม่ทำอะไร (ง่าย ๆ ก่อน)
        """
        ts = timestamp_ms if timestamp_ms is not None else int(datetime.now(timezone.utc).timestamp() * 1000)
        current_qty = self.hedge_position["qty"] if self.hedge_position else 0.0
        current_ratio = current_qty / net_spot_qty if net_spot_qty > 0 else 0.0

        if current_ratio >= target_ratio - 1e-6:
            # มี hedge พอแล้ว
            return

        add_ratio = target_ratio - current_ratio
        add_qty = net_spot_qty * add_ratio
        notional = add_qty * price
        required_margin = notional / max(self.hedge_leverage, 1)

        try:
            self._io_refresh_balances()
        except Exception as e:
            self.logger.log(f"[BAL] refresh futures available error: {e}", level="ERROR")

        if not getattr(self, "futures_available_margin", 0.0):
            self.logger.log(
                f"Date: {util.timemstamp_ms_to_date(ts)} - [HEDGE] skip add hedge (no futures balance snapshot)",
                level="INFO",
            )
            return

        if notional < self.min_hedge_notional:
            # notional เล็กเกินไป ไม่คุ้มเปิด
            return

        # margin guard
        if self.futures_available_margin <= 0:
            self.logger.log(
                f"Date: {util.timemstamp_ms_to_date(ts)} - [HEDGE] skip add hedge (available futures margin <= 0)",
                level="INFO",
            )
            return
        if required_margin > self.futures_available_margin:
            self.logger.log(
                f"Date: {util.timemstamp_ms_to_date(ts)} - [HEDGE] skip add hedge (req_margin={required_margin:.4f}, available={self.futures_available_margin:.4f}, "
                f"target_ratio={target_ratio:.2f}, net_spot={net_spot_qty:.4f})",
                level="INFO",
            )
            return

        # I/O layer: ให้ subclass ไป implement จริง
        hedge_entry_price = self._io_open_hedge_short(timestamp_ms=ts, qty=add_qty, price=price, reason=reason)
        if hedge_entry_price is None:
            # เปิด hedge ไม่สำเร็จ
            return

        if self.hedge_position is None:
            self.hedge_position = {"qty": add_qty, "entry": hedge_entry_price, "timestamp": ts}
            self.hedge_position["order_id"] = self._record_hedge_open(qty=add_qty, price=hedge_entry_price)
        else:
            # ถ้าเดิมมี hedge อยู่ → เฉลี่ยต้นทุน
            old = self.hedge_position
            new_qty = old["qty"] + add_qty
            new_entry = (old["entry"] * old["qty"] + hedge_entry_price * add_qty) / new_qty
            self.hedge_position["qty"] = new_qty
            self.hedge_position["entry"] = new_entry
            self.hedge_position["order_id"] = self._record_hedge_open(qty=add_qty, price=hedge_entry_price)
        # consume margin for backtest/paper tracking
        self.futures_available_margin = max(0.0, self.futures_available_margin - required_margin)

        self.logger.log(
            f"Date: {util.timemstamp_ms_to_date(ts)} - [HEDGE] scale-in {reason}: add_qty={add_qty:.4f}, "
            f"target_ratio={target_ratio:.2f}, "
            f"new_qty={self.hedge_position['qty']:.4f}, "
            f"entry={self.hedge_position['entry']:.4f}, "
            f"req_margin={required_margin:.4f}, avail_margin={self.futures_available_margin:.4f}",
            level="INFO",
        )
        # snapshot combined balance for hedge open
        try:
            self.record_hedge_balance(timestamp_ms=ts, current_price=price, notes="hedge_open")
        except Exception as e:
            self.logger.log(f"[HEDGE] record_hedge_balance open error: {e}", level="ERROR")

    # ------------------------------------------------------------------
    def _manage_hedge_exit(self, timestamp_ms: int, price: float, spot_unrealized: float, ema_fast: float, ema_mid: float) -> None:
        """
        ตัดสินใจปิด hedge:
        - ถ้ามี pending_recenter และ hedge PnL >= 0 → ทำ full recenter ที่นี่เลย
        - TP: กำไร hedge ชดเชย spot loss ตาม hedge_tp_ratio
        - SL: ถ้าราคาเด้งกลับ + hedge ขาดทุนเกิน hedge_sl_ratio
        """
        if self.hedge_position is None:
            return

        h = self.hedge_position
        hedge_qty = h["qty"]
        hedge_entry = h["entry"]

        # short: profit = (entry - price) * qty
        hedge_pnl = (hedge_entry - price) * hedge_qty

        # ----------------------------------------------------------
        # A) ถ้าอยู่ในโหมด "รอ recenter" จาก downtrend
        #    และ hedge PnL >= 0 → เรียก full recenter ตรงนี้
        # ----------------------------------------------------------
        if self.pending_recenter is not None and hedge_pnl >= 0:
            # ดึง ATR ล่าสุดจาก DB
            try:
                last = self.ohlcv_db.get_recent_ohlcv(self.symbol, 1)
                if last is not None and not last.empty:
                    row = last.iloc[-1].to_dict()
                    atr_14 = float(row.get("atr_14", 0.0) or 0.0)
                    atr_28 = float(row.get("atr_28", 0.0) or 0.0)
                else:
                    atr_14 = 0.0
                    atr_28 = 0.0
            except Exception as e:
                self.logger.log(
                    f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - [HEDGE] fetch ATR for recenter error: {e}",
                    level="ERROR",
                )
                atr_14 = 0.0
                atr_28 = 0.0

            self.logger.log(
                f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - [HEDGE] PnL >= 0 and pending_recenter set " f"→ trigger full recenter (pnl={hedge_pnl:.4f})",
                level="INFO",
            )

            # full recenter นี้จะ:
            # - ปิด hedge (ถ้า PnL ไม่ลบ)
            # - ใช้กำไร hedge ช่วย rebalance spot
            # - ล้าง grid เก่า + เปิด grid ใหม่
            self._do_full_recenter(
                timestamp_ms=timestamp_ms,
                price=price,
                atr_14=atr_14,
                atr_28=atr_28,
            )

            # เคลียร์ flag เพื่อกันไม่ให้ยิงซ้ำ
            self.pending_recenter = None
            return

        # ----------------------------------------------------------
        # B) เงื่อนไขเดิมของ hedge: MAX_LOSS / TP / SL / REVERSAL
        # ----------------------------------------------------------
        loss_to_cover = max(0.0, -spot_unrealized)
        max_loss_threshold = loss_to_cover * self.hedge_max_loss_ratio
        if max_loss_threshold > 0 and hedge_pnl <= -max_loss_threshold:
            self._close_hedge(timestamp_ms, price, reason="MAX_LOSS")
            self.pending_recenter = None  # กันไม่ให้ full recenter ซ้ำ
            return

        # TP: hedge profit covers spot loss * hedge_tp_ratio
        tp_threshold = loss_to_cover * self.hedge_tp_ratio

        if tp_threshold > 0 and hedge_pnl >= tp_threshold:
            self._close_hedge(timestamp_ms, price, reason="TP")
            # ใช้กำไร hedge มาลด spot ที่ขาดทุนหนัก ๆ
            self._rebalance_spot_after_hedge(
                timestamp_ms=timestamp_ms,
                hedge_pnl=hedge_pnl,
                price=price,
            )
            return

        # SL case: ราคาเด้งกลับ + EMA fast > EMA mid (reversal)
        reversal = price > ema_fast and ema_fast > ema_mid
        sl_threshold = abs(spot_unrealized) * self.hedge_sl_ratio

        if reversal and hedge_pnl <= -sl_threshold < 0:
            self._close_hedge(timestamp_ms, price, reason="SL_REVERSAL")
            self.pending_recenter = None  # กันไม่ให้ full recenter ซ้ำ
            return

        # Reversal cut after minimal hold if still losing
        hold_ms = 0
        try:
            if self.hedge_position and self.hedge_position.get("timestamp"):
                hold_ms = max(0, timestamp_ms - int(self.hedge_position["timestamp"]))
        except Exception:
            hold_ms = 0

        if reversal and hedge_pnl < 0 and hold_ms >= self.hedge_min_hold_ms:
            self._close_hedge(timestamp_ms, price, reason="REVERSAL_CUT")
            self.pending_recenter = None  # กันไม่ให้ full recenter ซ้ำ
            return

    # ------------------------------------------------------------------
    def _close_hedge(self, timestamp_ms: int, price: float, reason: str) -> None:
        """
        ปิด hedge ทั้งก้อน ผ่าน I/O layer แล้ว reset self.hedge_position
        """
        if self.hedge_position is None:
            return

        h = self.hedge_position
        qty = h["qty"]
        entry = h["entry"]

        hedge_notional = entry * qty
        locked_margin = hedge_notional / max(self.hedge_leverage, 1)
        pnl = (entry - price) * qty

        self._io_close_hedge(
            timestamp_ms=timestamp_ms,
            qty=qty,
            price=price,
            reason=reason,
        )

        if self.mode in ("backtest", "forward_test"):
            self.available_capital += pnl
            self.futures_available_margin = max(0.0, self.futures_available_margin + locked_margin + pnl)

        self.hedge_position = None

        try:

            self._record_hedge_close(close_price=price, realized_pnl=pnl)
            self.record_hedge_balance(timestamp_ms=timestamp_ms, current_price=price, notes="hedge_close")

        except Exception as e:
            self.logger.log(f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - [HEDGE] close error: {e}", level="ERROR")

        self.logger.log(
            f"Date: {util.timemstamp_ms_to_date(timestamp_ms)} - [HEDGE] CLOSE reason={reason}, qty={qty:.4f}, entry={entry:.4f}, " f"close={price:.4f}, pnl={pnl:.4f}",
            level="INFO",
        )

    # ------------------------------------------------------------------
    def _rebalance_spot_after_hedge(self, timestamp_ms: int, hedge_pnl: float, price: float) -> None:
        """
        ใช้กำไร hedge_pnl เป็น buffer ในการขาย spot ที่ขาดทุนแพง ๆ
        เป้าหมาย: ลด risk / ดึง equity กลับใกล้เงินต้น
        แนวคิด:
        - sort positions จาก entry สูง -> ต่ำ
        - ขายทิ้งทีละ position โดยเอากำไร hedge มารับ loss
        """
        if hedge_pnl <= 0 or not self.positions:
            return

        positions_sorted = sorted(self.positions, key=lambda p: p.entry_price, reverse=True)
        buffer = hedge_pnl
        new_positions = []

        for p in positions_sorted:
            pos_unreal = (price - p.entry_price) * p.qty  # มักจะติดลบ
            if pos_unreal >= 0:
                # position ที่ไม่ขาดทุน → ยังเก็บไว้
                new_positions.append(p)
                continue

            loss_if_sell = abs(pos_unreal)
            if loss_if_sell > buffer:
                # buffer ไม่พอรับ loss ของ position นี้ทั้งก้อน → เก็บไว้
                new_positions.append(p)
                continue

            # ขาย position นี้ทิ้ง ใช้ buffer รับ loss
            try:
                self._io_place_spot_sell(
                    timestamp_ms=timestamp_ms,
                    position=p,
                    sell_price=price,
                )
                buffer -= loss_if_sell
                self.logger.log(
                    f"Date {util.timemstamp_ms_to_date(timestamp_ms)} - [REBAL] cut spot entry={p.entry_price:.4f}, qty={p.qty:.4f}, " f"loss={pos_unreal:.4f}, buffer_left={buffer:.4f}",
                    level="INFO",
                )
            except Exception as e:
                self.logger.log(f"Date {util.timemstamp_ms_to_date(timestamp_ms)} - [REBAL] spot sell error: {e}", level="ERROR")
                new_positions.append(p)

        self.positions = new_positions

    # ------------------------------------------------------------------
    # Hedge persistence + balance helpers
    # ------------------------------------------------------------------
    def _record_hedge_open(self, qty: float, price: float) -> Optional[int]:
        """
        Persist hedge open into FuturesOrders. Returns row id if created.
        """
        if not hasattr(self, "futures_db") or self.futures_db is None:
            return None
        try:
            return self.futures_db.create_hedge_open(
                symbol=self.symbol_future or self.symbol,
                qty=qty,
                price=price,
                leverage=self.hedge_leverage,
            )
        except Exception as e:
            self.logger.log(f"[HEDGE] create_hedge_open error: {e}", level="ERROR")
            return None

    def _record_hedge_close(self, close_price: float, realized_pnl: float) -> None:
        if not hasattr(self, "futures_db") or self.futures_db is None:
            return
        order_id = None
        try:
            order_id = self.hedge_position.get("order_id") if self.hedge_position else None
        except Exception:
            order_id = None

        if order_id:
            try:
                self.futures_db.close_hedge_order(order_id=order_id, close_price=close_price, realized_pnl=realized_pnl)
                return
            except Exception as e:
                self.logger.log(f"[HEDGE] close_hedge_order error: {e}", level="ERROR")
        # fallback: close by symbol
        try:
            self.futures_db.close_open_orders_by_group(symbol=self.symbol_future or self.symbol, reason="HEDGE_CLOSE")
        except Exception as e:
            self.logger.log(f"[HEDGE] close_open_orders_by_group error: {e}", level="ERROR")

    def _refresh_balances_from_db_snapshot(self) -> None:
        """
        Refresh spot/futures available from AccountBalance latest rows.
        """
        if not hasattr(self, "acc_balance_db") or self.acc_balance_db is None:
            return

        # Backtest/forward_test: balances are simulated in-memory, do not read DB snapshots
        try:
            spot_row = self.acc_balance_db.get_latest_balance_by_type("SPOT", symbol=self.symbol)
            if spot_row:
                self.available_capital = float(spot_row.get("end_balance_usdt"))
            fut_row = self.acc_balance_db.get_latest_balance_by_type("FUTURES", symbol=self.symbol_future)
            if fut_row:
                self.futures_available_margin = float(fut_row.get("end_balance_usdt"))
        except Exception as e:
            self.logger.log(f"[BAL] refresh db error: {e}", level="ERROR")

    def _snapshot_account_balance(self, timestamp_ms: int, current_price: float, side: str, notes: str = "") -> None:
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

        equity = self._calc_equity(current_price)
        unrealized = self._calc_unrealized_pnl(current_price)
        realized_pnl = float(self.realized_grid_profit)
        # backtest: net_flow_usdt = 0 (ไม่มีฝากถอน), fees_usdt = 0 (ถ้ายังไม่ได้คิด fee)
        data = {
            "account_type": "COMBINED",
            "symbol": self.symbol,
            "side": side,
            "record_date": record_date,
            "record_time": record_time,
            "start_balance_usdt": round(equity, 6),
            "net_flow_usdt": round(realized_pnl, 6) - round(unrealized, 6),
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

    def record_hedge_balance(self, timestamp_ms: int, current_price: float, notes: str) -> None:
        """
        Record combined balance (spot + hedge unrealized) when hedge events occur.
        Live strategies may override to fetch real balances; default uses in-memory figures.
        """
        if not hasattr(self, "acc_balance_db") or self.acc_balance_db is None:
            return

        dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        spot_unreal = self._calc_unrealized_pnl(current_price)
        spot_value = sum(p.qty * current_price for p in self.positions)

        if notes == "hedge_close":
            hedge_unreal = 0.0

        try:
            if self.hedge_position:
                h = self.hedge_position
                hedge_unreal = (float(h["entry"]) - float(current_price)) * float(h["qty"])
        except Exception:
            hedge_unreal = 0.0

        combined_equity = float(self.available_capital + self.reserve_capital + spot_value + hedge_unreal)
        try:
            # combined snapshot
            self.acc_balance_db.insert_balance(
                {
                    "account_type": "COMBINED",
                    "symbol": self.symbol,
                    "record_date": dt.strftime("%Y-%m-%d"),
                    "record_time": dt.strftime("%H:%M:%S"),
                    "start_balance_usdt": round(combined_equity, 6),
                    "net_flow_usdt": round(float(self.realized_grid_profit), 6) - round(spot_unreal + hedge_unreal, 6),
                    "realized_pnl_usdt": round(float(self.realized_grid_profit), 6),
                    "unrealized_pnl_usdt": round(spot_unreal + hedge_unreal, 6),
                    "fees_usdt": 0.0,
                    "end_balance_usdt": round(combined_equity, 6),
                    "notes": notes,
                }
            )
            # futures snapshot uses available margin
            self.acc_balance_db.insert_balance(
                {
                    "account_type": "FUTURES",
                    "symbol": self.symbol_future,
                    "record_date": dt.strftime("%Y-%m-%d"),
                    "record_time": dt.strftime("%H:%M:%S"),
                    "start_balance_usdt": round(self.futures_available_margin, 6),
                    "net_flow_usdt": 0.0,
                    "realized_pnl_usdt": 0.0,
                    "unrealized_pnl_usdt": round(hedge_unreal, 6),
                    "fees_usdt": 0.0,
                    "end_balance_usdt": round(self.futures_available_margin, 6),
                    "notes": notes,
                }
            )
        except Exception as e:
            self.logger.log(f"[AccountBalance] record_hedge_balance error: {e}", level="ERROR")

    def _get_trend_direction(self, row: dict, price: float) -> str:
        ema_fast = float(row.get(f"ema_{self.ema_fast_period}", 0.0) or 0.0)
        ema_mid = float(row.get(f"ema_{self.ema_mid_period}", 0.0) or 0.0)
        ema_slow = float(row.get(f"ema_{self.ema_slow_period}", 0.0) or 0.0)

        # downtrend: price < fast < mid < slow)
        if price < ema_fast < ema_mid < ema_slow:
            return "down"

        # uptrend: price > fast > mid
        if price > ema_fast > ema_mid:
            return "up"

        return "sideways"

    def _compute_dynamic_order_size(self, remaining_slots: int) -> float:

        if remaining_slots <= 0:
            return 0.0

        safety_buffer_ratio = 0.1  # keep 10% of free cash as buffer
        min_order_usdt = 5.0  # don't place too tiny orders

        tradable_capital = self.available_capital * (1.0 - safety_buffer_ratio)
        if tradable_capital <= 0:
            return 0.0

        raw_size = tradable_capital / remaining_slots
        order_size_usdt = max(min_order_usdt, raw_size)

        return order_size_usdt
