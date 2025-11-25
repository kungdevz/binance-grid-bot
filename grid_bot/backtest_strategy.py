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
        self, symbol: str, symbol_future: str, initial_capital: float, grid_levels: int, atr_multiplier: float, order_size_usdt: float, reserve_ratio: float, logger: Optional[Logger] = None
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
    def _io_place_spot_sell(self, timestamp_ms: int, position: Position, sell_price: float) -> Dict[str, Any]:
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

    def _io_place_spot_buy(self, timestamp_ms: int, price: float, qty: float, grid_id: str) -> Dict[str, Any]:
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

    def _io_open_hedge_short(self, timestamp_ms: int, qty: float, price: float, reason: str) -> Optional[float]:
        """
        เปิด short futures จริง (live) หรือ mock (backtest)
        return: entry_price ถ้าสำเร็จ, None ถ้า fail
        """
        self.logger.log(
            f"Date: {datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} - [HEDGE_IO] open short backtest_strategy qty={qty:.4f} @ {price:.4f}, reason={reason}",
            level="INFO",
        )
        try:
            resp = self._mock_futures_order(self.symbol_future, "BUY", price, qty, leverage=self.hedge_leverage)
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
            f"Date: {datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} - [HEDGE_IO] close backtest_strategy stub qty={qty:.4f} @ {price:.4f}, reason={reason}",
            level="INFO",
        )
        try:
            resp = self._mock_futures_order(self.symbol_future, "SELL", price, qty, leverage=self.hedge_leverage)
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

    def _mock_order(self, symbol: str, side: str, price: float, qty: float):
        now_ms = int(datetime.now().timestamp() * 1000)
        order_id = now_ms
        client_order_id = f"mock-{order_id}"

        return {
            "info": {
                "symbol": symbol.replace("/", ""),  # BTCUSDT
                "orderId": order_id,
                "orderListId": "-1",
                "clientOrderId": client_order_id,
                "price": f"{price:.8f}",
                "origQty": f"{qty:.8f}",
                "executedQty": "0.00000000",
                "cummulativeQuoteQty": "0.00000000",
                "status": "NEW",
                "timeInForce": "GTC",
                "type": "LIMIT",
                "side": side.upper(),
                "stopPrice": "0.00000000",
                "icebergQty": "0.00000000",
                "time": now_ms,
                "updateTime": now_ms,
                "isWorking": True,
                "workingTime": now_ms,
                "origQuoteOrderQty": "0.00000000",
                "selfTradePreventionMode": "EXPIRE_MAKER",
            },
            # normalized fields (minimal subset)
            "id": str(order_id),
            "clientOrderId": client_order_id,
            "symbol": symbol,  # BTC/USDT
            "type": "limit",
            "timeInForce": "GTC",
            "side": side.lower(),
            "price": float(price),
            "amount": float(qty),
            "cost": 0.0,
            "average": None,
            "filled": 0.0,
            "remaining": float(qty),
            "status": "open",
            "timestamp": now_ms,
            "datetime": datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
            "lastTradeTimestamp": None,
            "lastUpdateTimestamp": now_ms,
            "postOnly": False,
            "reduceOnly": None,
            "stopPrice": None,
            "takeProfitPrice": None,
            "stopLossPrice": None,
            "trades": [],
            "fees": [],
            "fee": None,
        }

    def _mock_futures_order(self, symbol: str, side: str, price: float, qty: float, leverage: int):
        now_ms = int(datetime.now().timestamp() * 1000)
        order_id = now_ms
        client_order_id = f"mock-fut-{order_id}"
        return {
            "info": {
                "symbol": symbol.replace("/", ""),
                "orderId": order_id,
                "clientOrderId": client_order_id,
                "price": f"{price:.8f}",
                "origQty": f"{qty:.8f}",
                "executedQty": f"{qty:.8f}",
                "cumQuote": f"{qty * price:.8f}",
                "status": "FILLED",
                "type": "LIMIT",
                "side": side.upper(),
                "time": now_ms,
                "updateTime": now_ms,
                "reduceOnly": side.lower() == "buy",
                "positionSide": "BOTH",
                "leverage": leverage,
            }
        }

    def _build_spot_order_data(self, resp, grid_id):
        i = resp["info"]
        return {
            "grid_id": grid_id,
            "symbol": i["symbol"],
            "order_id": i["orderId"],
            "order_list_id": i.get("orderListId", "-1"),
            "client_order_id": i["clientOrderId"],
            "price": i["price"],
            "orig_qty": i["origQty"],
            "executed_qty": i["executedQty"],
            "cummulative_quote_qty": i["cummulativeQuoteQty"],
            "status": i["status"],
            "time_in_force": i["timeInForce"],
            "type": i["type"],
            "side": i["side"],
            "stop_price": i["stopPrice"],
            "iceberg_qty": i["icebergQty"],
            "binance_time": i["time"],
            "binance_update_time": i["updateTime"],
            "working_time": i.get("workingTime"),
            "is_working": int(i.get("isWorking", True)),
            "orig_quote_order_qty": i.get("origQuoteOrderQty", "0.00000000"),
            "self_trade_prevention_mode": i.get("selfTradePreventionMode"),
        }

    def _build_futures_order_data(self, resp):
        i = resp.get("info", resp)
        return {
            "order_id": i.get("orderId"),
            "client_order_id": i.get("clientOrderId"),
            "symbol": i.get("symbol"),
            "status": i.get("status", "NEW"),
            "type": i.get("type", "LIMIT"),
            "side": i.get("side"),
            "price": i.get("price"),
            "avg_price": i.get("avgPrice", i.get("price")),
            "orig_qty": i.get("origQty", i.get("orig_qty", 0)),
            "executed_qty": i.get("executedQty", 0),
            "cum_quote": i.get("cumQuote", i.get("cummulativeQuoteQty", 0)),
            "time_in_force": i.get("timeInForce", "GTC"),
            "stop_price": i.get("stopPrice", 0),
            "iceberg_qty": i.get("icebergQty", 0),
            "time": i.get("time"),
            "update_time": i.get("updateTime"),
            "is_working": int(i.get("isWorking", True)) if i.get("isWorking") is not None else 1,
            "position_side": i.get("positionSide", "BOTH"),
            "reduce_only": int(i.get("reduceOnly", False)),
            "close_position": int(i.get("closePosition", False)),
            "working_type": i.get("workingType", "CONTRACT_PRICE"),
            "price_protect": int(i.get("priceProtect", False)),
            "orig_type": i.get("origType", i.get("type", "LIMIT")),
            "margin_asset": i.get("marginAsset", "USDT"),
            "leverage": i.get("leverage"),
        }
