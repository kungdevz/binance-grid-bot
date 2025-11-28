# backtest_strategy.py
from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from grid_bot.database.logger import Logger
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
            self.logger.log(f"[BACKTEST] open hedge error: {e}", level="ERROR")
        return price

    def _io_close_hedge(self, timestamp_ms: int, qty: float, price: float, reason: str) -> None:
        """
        ปิด short futures จริง (BACKTEST) หรือ mock (backtest)
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
            self.logger.log(f"[BACKTEST] close hedge error: {e}", level="ERROR")

    def _io_refresh_balances(self) -> None:
        # backtest/forward ใช้ snapshot จาก DB
        try:
            self._refresh_balances_from_db_snapshot()
        except Exception as e:
            self.logger.log(f"[BAL][BACKTEST] refresh balances from DB error: {e}", level="ERROR")

    def _after_grid_sell(
        self,
        timestamp_ms: int,
        pos: Position,
        sell_price: float,
        notional: float,
        fee: float,
        pnl: float,
    ) -> None:
        """
        Accounting สำหรับ backtest/forward_test:
        - update available_capital / realized_grid_profit
        - snapshot account_balance
        """
        # 1) อัปเดตเงินสดและกำไรสะสม
        self.available_capital += notional - fee
        self.realized_grid_profit += pnl

        # 2) log รูปแบบเดิม (PAPER)
        self.logger.log(
            f"Date: {self.util.timemstamp_ms_to_date(timestamp_ms)} - [PAPER] Grid SELL: "
            f"entry={pos.entry_price}, target={pos.target_price}, sell={sell_price}, fee={fee:.4f}, "
            f"qty={pos.qty}, pnl={pnl}, total_realized={self.realized_grid_profit}",
            level="INFO",
        )

        # 3) snapshot ลง AccountBalance (ใช้ method เดิม)
        self._snapshot_account_balance(
            timestamp_ms=timestamp_ms,
            current_price=sell_price,
            side="SELL",
            notes=f"SELL @ {sell_price}",
        )

    def _after_grid_buy(
        self,
        timestamp_ms: int,
        grid_price: float,
        buy_price: float,
        qty: float,
        notional: float,
        fee: float,
    ) -> None:
        # หักเงินสดใน backtest
        total_cost = notional + fee
        self.available_capital = max(0.0, self.available_capital - total_cost)

        # snapshot ลง AccountBalance
        self._snapshot_account_balance(
            timestamp_ms=timestamp_ms,
            current_price=buy_price,
            side="BUY",
            notes=f"BUY @ {buy_price}",
        )

    def _refresh_balances_from_db_snapshot(self) -> None:
        """
        Refresh spot/futures available from AccountBalance latest rows.
        """
        if not hasattr(self, "acc_balance_db") or self.acc_balance_db is None:
            return

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
        if not self.is_paper_mode:
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

    def _record_hedge_balance(self, timestamp_ms: int, current_price: float, notes: str) -> None:
        if not hasattr(self, "acc_balance_db") or self.acc_balance_db is None:
            return

        dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        spot_unreal = self._calc_unrealized_pnl(current_price)
        spot_value = sum(p.qty * current_price for p in self.positions)

        # hedge_unreal default 0
        hedge_unreal = 0.0
        try:
            if notes == "hedge_close":
                hedge_unreal = 0.0
            if self.hedge_position:
                h = self.hedge_position
                hedge_unreal = (float(h["entry"]) - float(current_price)) * float(h["qty"])
        except Exception:
            hedge_unreal = 0.0

        combined_equity = float(self.available_capital + self.reserve_capital + spot_value + hedge_unreal)

        try:
            # SPOT snapshot
            self.acc_balance_db.insert_balance(
                {
                    "account_type": "SPOT",
                    "symbol": self.symbol,
                    "record_date": dt.strftime("%Y-%m-%d"),
                    "record_time": dt.strftime("%H:%M:%S"),
                    "start_balance_usdt": round(self.available_capital + self.reserve_capital + spot_value, 6),
                    "net_flow_usdt": 0.0,
                    "realized_pnl_usdt": round(self.realized_grid_profit, 6),
                    "unrealized_pnl_usdt": round(spot_unreal, 6),
                    "fees_usdt": 0.0,
                    "end_balance_usdt": round(self.available_capital + self.reserve_capital + spot_value, 6),
                    "notes": notes,
                }
            )
            # FUTURES snapshot
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
            # COMBINED snapshot
            self.acc_balance_db.insert_balance(
                {
                    "account_type": "COMBINED",
                    "symbol": self.symbol,
                    "record_date": dt.strftime("%Y-%m-%d"),
                    "record_time": dt.strftime("%H:%M:%S"),
                    "start_balance_usdt": round(combined_equity, 6),
                    "net_flow_usdt": 0.0,
                    "realized_pnl_usdt": round(self.realized_grid_profit, 6),
                    "unrealized_pnl_usdt": round(spot_unreal + hedge_unreal, 6),
                    "fees_usdt": 0.0,
                    "end_balance_usdt": round(combined_equity, 6),
                    "notes": notes,
                }
            )
        except Exception as e:
            self.logger.log(f"[AccountBalance] record_hedge_balance error: {e}", level="ERROR")
