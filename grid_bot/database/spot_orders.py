import mysql.connector
from typing import Any, Dict, List, Optional
from grid_bot.database.base_database import BaseMySQLRepo


class SpotOrders(BaseMySQLRepo):
    """
    CRUD operations for spot_orders table.
    """

    def __init__(self) -> None:
        super().__init__()
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            # Create spot_orders table if not exists
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS spot_orders (
                    id      BIGINT AUTO_INCREMENT PRIMARY KEY,
                    -- key ของ bot เอง
                    grid_id VARCHAR(64) NOT NULL,

                    -- จาก Binance /api/v3/order (FULL / RESULT response)
                    symbol    VARCHAR(32)  NOT NULL,              -- เช่น BTCUSDT
                    order_id  VARCHAR(255) NOT NULL,              -- orderId (long) ตาม spec
                    order_list_id BIGINT   NOT NULL DEFAULT -1,   -- -1 ถ้าไม่ใช่ OCO
                    client_order_id VARCHAR(64) NOT NULL,         -- clientOrderId (Binance จะใส่ให้ถ้าเราไม่ส่ง)

                    price                 DECIMAL(18, 8) NOT NULL DEFAULT '0.00000000',
                    orig_qty              DECIMAL(18, 8) NOT NULL DEFAULT '0.00000000',
                    executed_qty          DECIMAL(18, 8) NOT NULL DEFAULT '0.00000000',
                    cummulative_quote_qty DECIMAL(18, 8) NOT NULL DEFAULT '0.00000000',

                    status        VARCHAR(32) NOT NULL,   -- NEW, PARTIALLY_FILLED, FILLED, CANCELED ...
                    time_in_force VARCHAR(16) NOT NULL,   -- GTC, IOC, FOK
                    type          VARCHAR(32) NOT NULL,   -- LIMIT, MARKET, STOP_LOSS_LIMIT ...
                    side          VARCHAR(8)  NOT NULL,   -- BUY / SELL

                    stop_price    DECIMAL(18, 8) NOT NULL DEFAULT '0.00000000',
                    iceberg_qty   DECIMAL(18, 8) NOT NULL DEFAULT '0.00000000',

                    -- timestamp จาก Binance (ms)
                    binance_time        BIGINT NOT NULL,     -- time
                    binance_update_time BIGINT NOT NULL,     -- updateTime
                    working_time        BIGINT NULL,         -- workingTime (บางเคสอาจไม่มี/เปลี่ยน spec เลยเผื่อ NULL)

                    is_working TINYINT(1) NOT NULL,          -- isWorking: true/false -> 1/0

                    orig_quote_order_qty        DECIMAL(18, 8) NOT NULL DEFAULT '0.00000000',
                    self_trade_prevention_mode  VARCHAR(32) NULL,  -- EXPIRE_MAKER, NONE ... เผื่ออนาคต

                    -- timestamp ของ DB เอง
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

                    INDEX idx_spot_orders_symbol (symbol),
                    INDEX idx_spot_orders_grid_id (grid_id),
                    INDEX idx_spot_orders_order_id (order_id),
                    INDEX idx_spot_orders_created_at (created_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
            )

            conn.commit()
        finally:
            cursor.close()
            conn.close()

    def create_order(self, data: Dict[str, Any]) -> int:
        """
        Insert a new spot order (RAW Binance fields only). Returns the internal row id.
        """
        cols = [
            "grid_id",
            "symbol",
            "order_id",
            "order_list_id",
            "client_order_id",
            "price",
            "orig_qty",
            "executed_qty",
            "cummulative_quote_qty",
            "status",
            "time_in_force",
            "type",
            "side",
            "stop_price",
            "iceberg_qty",
            "binance_time",
            "binance_update_time",
            "working_time",
            "is_working",
            "orig_quote_order_qty",
            "self_trade_prevention_mode",
        ]

        placeholders = ", ".join("%s" for _ in cols)
        values = [data.get(col) for col in cols]

        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(f"INSERT INTO spot_orders ({', '.join(cols)}) VALUES ({placeholders})", values)
            row_id = cursor.lastrowid
            conn.commit()
            return row_id
        finally:
            cursor.close()
            conn.close()

    def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single spot order by Binance order_id."""

        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM spot_orders WHERE order_id = %s", (order_id,))
            row = cursor.fetchone()
            if not row:
                return None

            columns = [col[0] for col in cursor.description]

            return dict(zip(columns, row))
        finally:
            cursor.close()
            conn.close()

    def get_order_by_grid_id_and_price(self, grid_id: str, price: Any) -> Optional[Dict[str, Any]]:
        """Fetch a single spot order by Binance grid_id and price."""

        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT * FROM spot_orders WHERE grid_id = %s AND price = %s",
                (grid_id, price),
            )
            row = cursor.fetchone()
            if not row:
                return None

            columns = [col[0] for col in cursor.description]

            return dict(zip(columns, row))
        finally:
            cursor.close()
            conn.close()

    def list_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all spot orders, optionally filtered by symbol."""

        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            if symbol:
                cursor.execute(
                    "SELECT * FROM spot_orders WHERE symbol = %s ORDER BY binance_time",
                    (symbol,),
                )
            else:
                cursor.execute("SELECT * FROM spot_orders ORDER BY binance_time")

            rows = cursor.fetchall()
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in rows]
        finally:
            cursor.close()
            conn.close()

    def update_order(self, order_id: str, updates: Dict[str, Any]) -> None:
        """Update fields of a spot order by Binance order_id."""
        if not updates:
            return

        set_clause = ", ".join(f"{k} = %s" for k in updates.keys())
        values = list(updates.values()) + [order_id]

        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE spot_orders SET {set_clause} WHERE order_id = %s",
            values,
        )
        conn.commit()
        cursor.close()
        conn.close()

    def close_open_orders_by_group(self, symbol: str, grid_id: str, reason: str = "RECENTER") -> int:
        """
        Logical cancel: mark open orders in a grid group as CANCELED and not working.
        Schema has no reason column; reason is informational for logging.
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE spot_orders
                   SET status = 'CANCELED',
                       is_working = 0,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE symbol = %s
                   AND grid_id = %s
                   AND status IN ('NEW', 'PARTIALLY_FILLED')
                """,
                (symbol, grid_id),
            )
            conn.commit()
            return cursor.rowcount
        finally:
            cursor.close()
            conn.close()

    def delete_order(self, order_id: str) -> None:
        """Delete a spot order by Binance order_id."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM spot_orders WHERE order_id = %s", (order_id,))
        conn.commit()
        cursor.close()
        conn.close()
