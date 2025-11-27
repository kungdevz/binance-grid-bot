# backtest_strategy.py
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from grid_bot.database.logger import Logger
from grid_bot.database.spot_orders import SpotOrders
from grid_bot.database.future_orders import FuturesOrders
from grid_bot.utils.util import Util

from .base_strategy import BaseGridStrategy, Position


class BacktestGridStrategy(BaseGridStrategy):
    """
    Strategy สำหรับ backtest / forward_test
    - ไม่ยิงคำสั่งไป exchange จริง
    - จำลอง fill ทันที
    - DB ใช้เป็น log / record เท่านั้น
    """

    def __init__(self, symbol: str, symbol_future: str, initial_capital: float, grid_levels: int, atr_multiplier: float, reserve_ratio: float, logger: Optional[Logger] = None) -> None:
        super().__init__(
            symbol=symbol,
            symbol_future=symbol_future,
            initial_capital=initial_capital,
            grid_levels=grid_levels,
            atr_multiplier=atr_multiplier,
            reserve_ratio=reserve_ratio,
            mode="backtest",
            logger=logger,
        )

        self.logger.log("[BacktestGridStrategy] initialized", level="INFO")

    # ------------------------------------------------------------------
    # implement abstract I/O
    # ------------------------------------------------------------------
    def _io_place_spot_sell(self, timestamp_ms: int, position: Position, sell_price: float) -> Dict[str, Any]:
        """
        จำลอง SELL สำหรับ backtest
        - fill ทันที
        - ฟอร์แมต field ให้เหมือน live (_build_spot_order_data)
        """
        resp = self.util._mock_spot_order(
            symbol=position.symbol,
            side="SELL",
            price=position.entry_price,
            qty=position.qty,
            timestamp_ms=position.opened_at,
            grid_id=position.group_id,
        )
        data = self.util._build_spot_order_data(resp, grid_id=position.group_id)

        try:
            self.spot_orders_db.create_order(data)
        except Exception as e:
            self.logger.log(f"[Backtest] create_order SELL error: {e}", level="ERROR")

        return data

    def _io_place_spot_buy(self, timestamp_ms: int, price: float, qty: float, grid_id: str) -> Dict[str, Any]:
        """
        จำลองว่า order ถูก fill ทันที (BACKTEST)
        เขียนลง SpotOrders DB ในรูปแบบ field เดียวกับ live (_build_spot_order_data)
        """
        resp = self.util._mock_spot_order(symbol=self.symbol, side="BUY", price=price, qty=qty, timestamp_ms=timestamp_ms, grid_id=grid_id)
        data = self.util._build_spot_order_data(resp, grid_id=grid_id)

        try:
            self.spot_orders_db.create_order(data)
        except Exception as e:
            self.logger.log(f"[Backtest] create_order BUY error: {e}", level="ERROR")

        return data

    def _run(self, file_path: Optional[str] = None) -> None:
        """
        Execute a backtest over a CSV OHLCV file.
        If file_path is None, fall back to env OHLCV_FILE.
        """
        file_path = file_path or os.getenv("OHLCV_FILE")
        if not file_path or not os.path.exists(file_path):
            raise ValueError("OHLCV_FILE must be set in env or config for backtest and point to an existing file")

        self.logger.log(f"Loading OHLCV data from {file_path}", level="INFO")
        df = pd.read_csv(file_path, parse_dates=["Time"])
        df.rename(columns={"Time": "time", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}, inplace=True)
        df.set_index("time", inplace=True)
        df_history = df.iloc[:100]

        for idx, row in df.iloc[100:].iterrows():
            ts = int(idx.value // 10**6)  # Timestamp → ms
            self.on_bar(ts, float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"]), float(row["volume"]), df_history)
        return None

    def _io_open_hedge_short(self, timestamp_ms: int, qty: float, price: float, reason: str) -> Optional[float]:
        """
        เปิด short futures จริง (live) หรือ mock (backtest)
        return: entry_price ถ้าสำเร็จ, None ถ้า fail
        """
        self.logger.log(f"Date: {self.util.timemstamp_ms_to_date(timestamp_ms)} - [HEDGE_IO] open short backtest_strategy qty={qty:.4f} @ {price:.4f}, reason={reason}", level="INFO")
        try:
            resp = self.util._mock_futures_order(self.symbol_future, "BUY", price, qty, leverage=self.hedge_leverage)
            avg_price = float(resp.get("info", {}).get("price", price)) if isinstance(resp, dict) else price
            self.futures_db.create_hedge_open(symbol=self.symbol_future, qty=qty, price=avg_price, leverage=self.hedge_leverage)
            return avg_price
        except Exception as e:
            self.logger.log(f"[Live] open hedge error: {e}", level="ERROR")
        return price

    def _io_close_hedge(self, timestamp_ms: int, qty: float, price: float, reason: str) -> None:
        """
        ปิด short futures จริง (live) หรือ mock (backtest)
        """
        self.logger.log(
            f"Date: {self.util.timemstamp_ms_to_date(timestamp_ms)} - [HEDGE_IO] close backtest_strategy stub qty={qty:.4f} @ {price:.4f}, reason={reason}",
            level="INFO",
        )
        try:
            resp = self.util._mock_futures_order(self.symbol_future, "SELL", price, qty, leverage=self.hedge_leverage)
            pnl = 0.0
            try:
                info = resp.get("info", {})
                entry = float(info.get("price", price))
                pnl = (entry - price) * qty
            except Exception:
                pnl = 0.0
            self.futures_db.close_hedge_order(order_id=resp.get("info", {}).get("orderId", 0), close_price=price, realized_pnl=pnl)
        except Exception as e:
            self.logger.log(f"[Live] close hedge error: {e}", level="ERROR")

    def _io_refresh_balances(self) -> None:
        # backtest/forward ใช้ snapshot จาก DB
        try:
            self._refresh_balances_from_db_snapshot()
        except Exception as e:
            self.logger.log(f"[BAL][BACKTEST] refresh balances from DB error: {e}", level="ERROR")
