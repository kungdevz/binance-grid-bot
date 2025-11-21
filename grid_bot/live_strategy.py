# live_strategy.py
from __future__ import annotations
from typing import Any, Dict, Optional

from grid_bot.exchange import ExchangeSync
from grid_bot.database.logger import Logger
from grid_bot.utils import util

from .base_strategy import BaseGridStrategy, Position

class LiveGridStrategy(BaseGridStrategy):
    """
    Strategy สำหรับ live trading
    - ใช้ ExchangeSync (ccxt) ยิงคำสั่งจริง
    - sync กับ DB จริง
    """

    def __init__(
        self,
        symbol_spot: str,
        symbol_future: str,
        initial_capital: float,
        grid_levels: int,
        atr_multiplier: float,
        order_size_usdt: float,
        reserve_ratio: float,
        logger: Optional[Logger] = None,
    ) -> None:
        super().__init__(
            symbol=symbol_spot,
            symbol_future=symbol_future,
            initial_capital=initial_capital,
            grid_levels=grid_levels,
            atr_multiplier=atr_multiplier,
            order_size_usdt=order_size_usdt,
            reserve_ratio=reserve_ratio,
            mode="live",
            logger=logger,
        )

        self.exchange = ExchangeSync(symbol_spot=symbol_spot, symbol_future=symbol_future, mode="live")

        self.logger.log("[LiveGridStrategy] initialized", level="INFO")

    # สามารถ sync order/position จาก exchange -> DB ตอนเริ่มต้นได้ที่นี่ถ้าต้องการ
    # ------------------------------------------------------------------
    # implement abstract I/O
    # ------------------------------------------------------------------

    def _io_place_spot_buy(
        self,
        timestamp_ms: int,
        price: float,
        qty: float,
        grid_id: str,
    ) -> Dict[str, Any]:
        """
        ยิง limit buy จริงผ่าน ExchangeSync แล้วเขียน DB
        """
        resp = self.exchange.place_limit_buy(self.symbol, price, qty, exchange=True)

        # แปลง response เป็นรูปแบบเดียวกับ SpotOrders
        order_data = self.exchange._build_spot_order_data(resp, grid_id)
        try:
            self.spot_orders_db.create_order(order_data)
        except Exception as e:
            self.logger.log(f"[Live] create_order error: {e}", level="ERROR")

        return order_data

    def _io_place_spot_sell(
        self,
        timestamp_ms: int,
        position: Position,
        sell_price: float,
    ) -> Dict[str, Any]:
        
        qty = position.qty
        resp = self.exchange.place_limit_sell(self.symbol, sell_price, qty, exchange=True)
        order_data = self.exchange._build_spot_order_data(resp, position.group_id)
        
        try:
            self.spot_orders_db.create_order(order_data)
        except Exception as e:
            self.logger.log(f"[Live] create_order error: {e}", level="ERROR")

        return order_data

    def _io_open_hedge(
        self,
        timestamp_ms: int,
        notional_usdt: float,
        price: float,
    ) -> Optional[Dict[str, Any]]:
        """
        เปิด short futures จริง
        สมมติว่า ExchangeSync มี method open_short / place_futures_order ฯลฯ
        """
        # TODO: เปลี่ยนเป็น method จริงใน ExchangeSync ที่มีอยู่
        try:
            # ตัวอย่าง pseudo:
            qty = notional_usdt / price
            resp = self.exchange.place_futures_short(self.symbol_future, price, qty, leverage=2)
            data = self.exchange._build_futures_order_data(resp)
            self.futures_db.create_order(data)
            return data
        except Exception as e:
            self.logger.log(f"[Live] open hedge error: {e}", level="ERROR")
            return None

    def _io_close_hedge(
        self,
        timestamp_ms: int,
    ) -> Optional[Dict[str, Any]]:
        """
        ปิด short hedge ทั้งหมด (pseudo code)
        """
        # TODO: ใช้ method จริงจาก ExchangeSync / FuturesOrders เพื่อตรวจ position แล้วปิด
        try:
            # resp = self.exchange.close_all_futures_short(self.symbol_future)
            # data = ...
            # self.futures_db.create_order(data)
            return None
        except Exception as e:
            self.logger.log(f"[Live] close hedge error: {e}", level="ERROR")
            return None
