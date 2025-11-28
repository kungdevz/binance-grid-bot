from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
from grid_bot.database.base_database import BaseMySQLRepo


class FuturesOrders(BaseMySQLRepo):
    """
    CRUD operations for futures_orders table.
    """

    def __init__(self) -> None:
        super().__init__()
        conn = self._get_conn()
        cursor = conn.cursor()
        # Create futures_orders table
        try:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS `futures_orders` (
                    `id` INT AUTO_INCREMENT PRIMARY KEY,              -- ไอดีอัตโนมัติ
                    `order_id` BIGINT NOT NULL UNIQUE,                -- รหัสคำสั่ง (ไม่ซ้ำ)
                    `client_order_id` VARCHAR(64),                    -- รหัสคำสั่งจาก client
                    `symbol` VARCHAR(32) NOT NULL,                    -- สัญลักษณ์คู่เทรด
                    `status` VARCHAR(32) NOT NULL,                    -- สถานะคำสั่ง
                    `type` VARCHAR(32) NOT NULL,                      -- ประเภทคำสั่ง
                    `side` VARCHAR(16) NOT NULL,                      -- Buy / Sell
                    `price` DECIMAL(18,8) NOT NULL,                   -- ราคาที่ตั้ง
                    `avg_price` DECIMAL(18,8) NOT NULL DEFAULT 0,     -- ราคาเฉลี่ยที่ได้
                    `orig_qty` DECIMAL(18,8) NOT NULL,                -- ปริมาณเริ่มต้น
                    `executed_qty` DECIMAL(18,8) NOT NULL,            -- ปริมาณที่ถูกเทรดแล้ว
                    `cum_quote` DECIMAL(18,8) NOT NULL DEFAULT 0,     -- มูลค่ารวม quote asset
                    `time_in_force` VARCHAR(16),                      -- ระยะเวลาคำสั่งมีผล
                    `stop_price` DECIMAL(18,8) NOT NULL DEFAULT 0,    -- Stop price
                    `iceberg_qty` DECIMAL(18,8) NOT NULL DEFAULT 0,   -- Iceberg quantity
                    `time` BIGINT NOT NULL,                           -- เวลาสร้าง (epoch)
                    `update_time` BIGINT NOT NULL,                    -- เวลาล่าสุด (epoch)
                    `is_working` TINYINT(1) NOT NULL DEFAULT 1,       -- ยัง active หรือไม่
                    `position_side` VARCHAR(16) DEFAULT 'BOTH',       -- ฝั่ง position
                    `reduce_only` TINYINT(1) NOT NULL DEFAULT 0,      -- Reduce only flag
                    `close_position` TINYINT(1) NOT NULL DEFAULT 0,   -- ปิด position flag
                    `working_type` VARCHAR(32) DEFAULT 'CONTRACT_PRICE', -- ประเภทการทำงาน
                    `price_protect` TINYINT(1) NOT NULL DEFAULT 0,    -- ป้องกันราคา
                    `orig_type` VARCHAR(32),                          -- ประเภทคำสั่งต้นฉบับ
                    `margin_asset` VARCHAR(16),                       -- สินทรัพย์ margin
                    `leverage` INT                                    -- เลเวอเรจ
                    )
                """
            )

            cursor.execute(
                """
                SELECT COUNT(1) FROM INFORMATION_SCHEMA.STATISTICS
                WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = 'futures_orders'
                AND INDEX_NAME = 'idx_futures_orders_symbol';
            """
            )

            if cursor.fetchone()[0] == 0:
                cursor.execute("CREATE INDEX idx_futures_orders_symbol ON futures_orders(symbol)")

            cursor.execute(
                """
                SELECT COUNT(1) FROM INFORMATION_SCHEMA.STATISTICS
                WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = 'futures_orders'
                AND INDEX_NAME = 'idx_futures_orders_time';
            """
            )

            if cursor.fetchone()[0] == 0:
                cursor.execute("CREATE INDEX idx_futures_orders_time ON futures_orders(time)")

            conn.commit()

        finally:
            cursor.close()
            conn.close()

    def create_order(self, data: Dict[str, Any]) -> str:
        """
        Insert a new futures order. Returns the internal row id.
        """
        cols = [
            "order_id",
            "client_order_id",
            "symbol",
            "status",
            "type",
            "side",
            "price",
            "avg_price",
            "orig_qty",
            "executed_qty",
            "cum_quote",
            "time_in_force",
            "stop_price",
            "iceberg_qty",
            "time",
            "update_time",
            "is_working",
            "position_side",
            "reduce_only",
            "close_position",
            "working_type",
            "price_protect",
            "orig_type",
            "margin_asset",
            "leverage",
        ]
        placeholders = ", ".join("%s" for _ in cols)
        values = [data.get(col) for col in cols]

        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                f"INSERT INTO futures_orders ({', '.join(cols)}) VALUES ({placeholders})",
                values,
            )
            conn.commit()
            return data.get("order_id")
        finally:
            cursor.close()
            conn.close()

    def get_order(self, order_id: int) -> Optional[Dict[str, Any]]:
        """Fetch a single futures order by Binance order_id."""
        conn = self._get_conn()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT * FROM futures_orders WHERE order_id = %s", (order_id,))
            row = cursor.fetchone()
            return row
        finally:
            cursor.close()
            conn.close()

    def list_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all futures orders, optionally filtered by symbol."""
        conn = self._get_conn()
        cursor = conn.cursor(dictionary=True)
        try:
            if symbol:
                cursor.execute("SELECT * FROM futures_orders WHERE symbol = %s ORDER BY time", (symbol,))
            else:
                cursor.execute("SELECT * FROM futures_orders ORDER BY time")
            rows = cursor.fetchall()
            return rows
        finally:
            cursor.close()
            conn.close()

    def update_order(self, order_id: int, updates: Dict[str, Any]) -> None:
        """Update fields of a futures order by Binance order_id."""
        if not updates:
            return
        set_clause = ", ".join(f"{k} = %s" for k in updates.keys())
        values = list(updates.values()) + [order_id]

        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(f"UPDATE futures_orders SET {set_clause} WHERE order_id = %s", values)
            conn.commit()
        finally:
            cursor.close()
            conn.close()

    def delete_order(self, order_id: int) -> None:
        """Delete a futures order by Binance order_id."""
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM futures_orders WHERE order_id = %s", (order_id,))
            conn.commit()
        finally:
            cursor.close()
            conn.close()

    def close_open_orders_by_group(self, symbol: str, reason: str = "RECENTER") -> int:
        """
        Logical cancel: mark open futures orders for a symbol as canceled/closed.
        Futures table has no grid_id; scope by symbol only.
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE futures_orders
                   SET status = 'CANCELED',
                       is_working = 0,
                       update_time = UNIX_TIMESTAMP() * 1000
                 WHERE symbol = %s
                   AND status IN ('NEW', 'PARTIALLY_FILLED')
                """,
                (symbol,),
            )
            conn.commit()
            return cursor.rowcount
        finally:
            cursor.close()
            conn.close()

    def create_hedge_open(self, symbol: str, qty: float, price: float, leverage: int, side: str = "SELL") -> int:
        """
        Convenience wrapper to record a hedge open.
        """
        data = {
            "order_id": int(datetime.now().timestamp() * 1000),
            "client_order_id": self.util.generate_order_id("HEDGE_OPEN"),
            "symbol": symbol,
            "status": "OPEN",
            "type": "LIMIT",
            "side": side,
            "price": price,
            "avg_price": price,
            "orig_qty": qty,
            "executed_qty": qty,
            "cum_quote": qty * price,
            "time_in_force": "GTC",
            "stop_price": 0,
            "iceberg_qty": 0,
            "time": int(datetime.now().timestamp() * 1000),
            "update_time": int(datetime.now().timestamp() * 1000),
            "is_working": 1,
            "position_side": "BOTH",
            "reduce_only": 0,
            "close_position": 0,
            "working_type": "CONTRACT_PRICE",
            "price_protect": 0,
            "orig_type": "LIMIT",
            "margin_asset": "USDT",
            "leverage": leverage,
        }
        return self.create_order(data)

    def close_hedge_order(self, order_id: int, close_price: float, realized_pnl: float) -> None:
        """
        Mark a hedge order as closed with realized pnl.
        """
        self.update_order(
            order_id=order_id,
            updates={
                "status": "CLOSED",
                "avg_price": close_price,
                "update_time": int(datetime.utcnow().timestamp() * 1000),
                "cum_quote": realized_pnl,
                "is_working": 0,
            },
        )
