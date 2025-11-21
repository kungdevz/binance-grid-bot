# backtest_strategy.py
from __future__ import annotations

import pandas as pd
import numpy as np
import os

from datetime import datetime
from typing import Any, Dict, Optional

from grid_bot.database.logger import Logger
from grid_bot.database.spot_orders import SpotOrders
from grid_bot.database.future_orders import FuturesOrders
from grid_bot.utils import util

from .base_strategy import BaseGridStrategy, Position


class BacktestGridStrategy(BaseGridStrategy):
    """
    Strategy สำหรับ backtest / forward_test
    - ไม่ยิงคำสั่งไป exchange จริง
    - จำลอง fill ทันที
    - DB ใช้เป็น log / record เท่านั้น
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
        logger: Optional[Logger] = None,
    ) -> None:
        super().__init__(
            symbol=symbol,
            symbol_future=symbol_future,
            initial_capital=initial_capital,
            grid_levels=grid_levels,
            atr_multiplier=atr_multiplier,
            order_size_usdt=order_size_usdt,
            reserve_ratio=reserve_ratio,
            mode="backtest",
            logger=logger,
        )

        self.logger.log("[BacktestGridStrategy] initialized", level="INFO")

    # ------------------------------------------------------------------
    # implement abstract I/O
    # ------------------------------------------------------------------
    def _io_place_spot_sell(
        self,
        timestamp_ms: int,
        position: Position,
        sell_price: float,
    ) -> Dict[str, Any]:
        """
        จำลอง SELL สำหรับ backtest
        - fill ทันที
        - ฟอร์แมต field ให้เหมือน live (_build_spot_order_data)
        """
        now_ms = int(timestamp_ms or int(datetime.now().timestamp() * 1000))
        order_id = util.generate_order_id("SELL")
        client_order_id = f"bt-{order_id}"
        qty = position.qty
        notional = sell_price * qty

        data = {
            "grid_id": position.group_id,
            "symbol": self.symbol,
            "order_id": order_id,
            "order_list_id": "-1",
            "client_order_id": client_order_id,
            "price": f"{sell_price:.8f}",
            "orig_qty": f"{qty:.8f}",
            "executed_qty": f"{qty:.8f}",
            "cummulative_quote_qty": f"{notional:.8f}",
            "status": "FILLED",
            "time_in_force": "GTC",
            "type": "LIMIT",
            "side": "SELL",
            "stop_price": "0.00000000",
            "iceberg_qty": "0.00000000",
            "binance_time": now_ms,
            "binance_update_time": now_ms,
            "working_time": now_ms,
            "is_working": 1,
            "orig_quote_order_qty": f"{notional:.8f}",
            "self_trade_prevention_mode": "EXPIRE_MAKER",
        }

        try:
            self.spot_orders_db.create_order(data)
        except Exception as e:
            self.logger.log(f"[Backtest] create_order SELL error: {e}", level="ERROR")

        return data

    def _io_place_spot_buy(
        self,
        timestamp_ms: int,
        price: float,
        qty: float,
        grid_id: str,
    ) -> Dict[str, Any]:
        """
        จำลองว่า order ถูก fill ทันที (BACKTEST)
        เขียนลง SpotOrders DB ในรูปแบบ field เดียวกับ live (_build_spot_order_data)
        """
        now_ms = int(timestamp_ms or int(datetime.now().timestamp() * 1000))
        order_id = util.generate_order_id("BUY")
        client_order_id = f"bt-{order_id}"
        notional = price * qty

        data = {
            "grid_id": grid_id,
            "symbol": self.symbol,
            "order_id": order_id,
            "order_list_id": "-1",
            "client_order_id": client_order_id,
            "price": f"{price:.8f}",
            "orig_qty": f"{qty:.8f}",
            "executed_qty": f"{qty:.8f}",
            "cummulative_quote_qty": f"{notional:.8f}",
            "status": "FILLED",
            "time_in_force": "GTC",
            "type": "LIMIT",
            "side": "BUY",
            "stop_price": "0.00000000",
            "iceberg_qty": "0.00000000",
            "binance_time": now_ms,
            "binance_update_time": now_ms,
            "working_time": now_ms,
            "is_working": 1,
            "orig_quote_order_qty": f"{notional:.8f}",
            "self_trade_prevention_mode": "EXPIRE_MAKER",
        }

        try:
            self.spot_orders_db.create_order(data)
        except Exception as e:
            self.logger.log(f"[Backtest] create_order BUY error: {e}", level="ERROR")

        return data

    def _run(self, timestamp_ms):
        file_path = os.getenv("OHLCV_FILE")
        if not file_path or not os.path.exists(file_path):
            raise ValueError("OHLCV_FILE must be set in env or config for backtest and point to an existing file")

        self.logger.log(f"Loading OHLCV data from {file_path}", level="INFO")
        df = pd.read_csv(file_path, parse_dates=["Time"])
        df.rename(
            columns={
                "Time": "time",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            },
            inplace=True,
        )
        df.set_index("time", inplace=True)
        df_history = df.iloc[:100]

        for idx, row in df.iloc[100:].iterrows():
            ts = int(idx.value // 10**6)  # Timestamp → ms
            self.on_bar(
                ts,
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
                float(row["volume"]),
                df_history,
            )
        return None

    def _io_open_hedge_short(self, qty: float, price: float, reason: str) -> Optional[float]:
        """
        เปิด short futures จริง (live) หรือ mock (backtest)
        return: entry_price ถ้าสำเร็จ, None ถ้า fail
        """
        self.logger.log(
            f"[HEDGE_IO] open short stub qty={qty:.4f} @ {price:.4f}, reason={reason}",
            level="DEBUG",
        )
        # backtest แบบง่าย ๆ: assume filled ทันทีที่ price ปัจจุบัน
        return price

    def _io_close_hedge(self, qty: float, price: float, reason: str) -> None:
        """
        ปิด short futures จริง (live) หรือ mock (backtest)
        """
        self.logger.log(
            f"[HEDGE_IO] close short stub qty={qty:.4f} @ {price:.4f}, reason={reason}",
            level="DEBUG",
        )
