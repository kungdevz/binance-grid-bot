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

    def _io_place_spot_buy(self, timestamp_ms: int, price: float, qty: float, grid_id: str) -> Dict[str, Any]:
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

    def _io_place_spot_sell(self, timestamp_ms: int, position: Position, sell_price: float) -> Dict[str, Any]:

        qty = position.qty
        resp = self.exchange.place_limit_sell(self.symbol, sell_price, qty, exchange=True)
        order_data = self.exchange._build_spot_order_data(resp, position.group_id)

        try:
            self.spot_orders_db.create_order(order_data)
        except Exception as e:
            self.logger.log(f"[Live] create_order error: {e}", level="ERROR")

        return order_data

    def _io_open_hedge_short(self, qty: float, price: float, reason: str) -> Optional[float]:
        self.logger.log(f"[HEDGE_IO] open short live_strategy qty={qty:.4f} @ {price:.4f}, reason={reason}", level="DEBUG")
        try:
            resp = self.exchange.place_futures_short(self.symbol_future, price, qty, leverage=self.hedge_leverage, exchange=True)
            avg_price = float(resp.get("info", {}).get("price", price)) if isinstance(resp, dict) else price
            self.futures_db.create_hedge_open(symbol=self.symbol_future, qty=qty, price=avg_price, leverage=self.hedge_leverage)
            return avg_price
        except Exception as e:
            self.logger.log(f"[Live] open hedge error: {e}", level="ERROR")
            return None

    def _io_close_hedge(self, qty: float, price: float, reason: str) -> None:
        try:
            resp = self.exchange.close_futures_position(self.symbol_future, qty=qty, price=price, exchange=True)
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

    # Balance sync
    def sync_balances_to_db(self) -> None:
        try:
            spot_bal = self.exchange.fetch_spot_balance()
            usdt_spot = spot_bal.get("USDT", {}) if isinstance(spot_bal, dict) else {}
            spot_total = float(usdt_spot.get("total", 0.0))
            spot_free = float(usdt_spot.get("free", spot_total))
            self.acc_balance_db.insert_balance_with_type("SPOT", balance_usdt=spot_total, available_usdt=spot_free, notes="LIVE")
        except Exception as e:
            self.logger.log(f"[BAL] sync spot error: {e}", level="ERROR")

        try:
            fut_bal = self.exchange.fetch_futures_balance()
            info = fut_bal.get("info", {}) if isinstance(fut_bal, dict) else {}
            total_wallet = float(info.get("totalWalletBalance", 0.0) or fut_bal.get("total", 0.0))
            available = float(info.get("availableBalance", 0.0) or fut_bal.get("free", 0.0))
            self.acc_balance_db.insert_balance_with_type("FUTURES", balance_usdt=total_wallet, available_usdt=available, notes="LIVE")
        except Exception as e:
            self.logger.log(f"[BAL] sync futures error: {e}", level="ERROR")
