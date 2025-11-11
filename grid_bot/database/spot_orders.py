import mysql.connector
from typing import Any, Dict, List, Optional, Tuple
from grid_bot.database.base_database import BaseMySQLRepo


class SpotOrders(BaseMySQLRepo):
    """
    CRUD operations for spot_orders table.
    """

    def __init__(self) -> None:
        conn = self._get_conn()
        cursor = conn.cursor()
        # Create spot_orders table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS spot_orders (
                id                     BIGINT AUTO_INCREMENT PRIMARY KEY,
                order_id               VARCHAR(64)  NOT NULL,
                client_order_id        VARCHAR(64),
                grid_id                VARCHAR(64)  NOT NULL,
                symbol                 VARCHAR(32)  NOT NULL,
                status                 VARCHAR(32)  NOT NULL,
                type                   VARCHAR(32)  NOT NULL,
                side                   VARCHAR(8)   NOT NULL,
                price                  DOUBLE       NOT NULL,
                avg_price              DOUBLE       DEFAULT 0,
                orig_qty               DOUBLE       DEFAULT 0,
                executed_qty           DOUBLE       DEFAULT 0,
                cummulative_quote_qty  DOUBLE       DEFAULT 0,
                time_in_force          VARCHAR(16),
                stop_price             DOUBLE       DEFAULT 0,
                iceberg_qty            DOUBLE       DEFAULT 0,
                time                   DATETIME DEFAULT CURRENT_TIMESTAMP,
                update_time            DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                is_working             TINYINT(1)   DEFAULT 1,
                INDEX idx_spot_orders_symbol (symbol),
                INDEX idx_spot_orders_time (time)
            )
        """)

        cursor.execute("""
            SELECT COUNT(1) FROM INFORMATION_SCHEMA.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
            AND TABLE_NAME = 'spot_orders'
            AND INDEX_NAME = 'idx_spot_orders_symbol';
        """)
        
        if cursor.fetchone()[0] == 0:
            cursor.execute("CREATE INDEX idx_spot_orders_symbol ON spot_orders(symbol)")

        cursor.execute("""
            SELECT COUNT(1) FROM INFORMATION_SCHEMA.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
            AND TABLE_NAME = 'spot_orders'
            AND INDEX_NAME = 'idx_spot_orders_time';
        """)
        
        if cursor.fetchone()[0] == 0:
            cursor.execute("CREATE INDEX idx_spot_orders_time ON spot_orders(time)")
        
        conn.commit()
        cursor.close()
        conn.close()

    def create_order(self, data: Dict[str, Any]) -> int:
        """
        Insert a new spot order. Returns the internal row id.
        """
        cols = [
            "order_id", "client_order_id", "grid_id", "symbol", "status", "type", "side", "price", 
            "avg_price", "orig_qty", "executed_qty", "cummulative_quote_qty", "time_in_force", 
            "stop_price", "iceberg_qty", "time", "update_time", "is_working"
        ]
        placeholders = ", ".join("%s" for _ in cols)
        values = [data.get(col) for col in cols]

        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            f"INSERT INTO spot_orders ({', '.join(cols)}) VALUES ({placeholders})",
            values
        )
        row_id = cursor.lastrowid
        conn.commit()
        cursor.close()
        conn.close()
        return row_id

    def get_order(self, order_id: int) -> Optional[Dict[str, Any]]:
        """Fetch a single spot order by Binance order_id."""
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM spot_orders WHERE order_id = %s", (order_id,)
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if not row:
            return None
        columns = [col[0] for col in cursor.description]
        return dict(zip(columns, row))

    def list_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all spot orders, optionally filtered by symbol."""
        conn = self.get_conn()
        cursor = conn.cursor()
        if symbol:
            cursor.execute(
                "SELECT * FROM spot_orders WHERE symbol = %s ORDER BY time", (symbol,)
            )
        else:
            cursor.execute("SELECT * FROM spot_orders ORDER BY time")
        rows = cursor.fetchall()
        columns = [col[0] for col in cursor.description]
        conn.close()
        return [dict(zip(columns, row)) for row in rows]

    def update_order(self, order_id: int, updates: Dict[str, Any]) -> None:
        """Update fields of a spot order by Binance order_id."""
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        values = list(updates.values()) + [order_id]

        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE spot_orders SET {set_clause} WHERE order_id = %s", values
        )
        conn.commit()
        conn.close()

    def delete_order(self, order_id: int) -> None:
        """Delete a spot order by Binance order_id."""
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM spot_orders WHERE order_id = %s", (order_id,)
        )
        conn.commit()
        conn.close()
