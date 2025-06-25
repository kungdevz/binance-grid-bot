import sqlite3
from typing import Any, Dict, List, Optional, Tuple

class FuturesOrdersDB:
    """
    CRUD operations for futures_orders table.
    """
    def __init__(self, db_path: str = "db/backtest_bot.db"):
        self.db_path = db_path
        self._init_schema()

    def _init_schema(self) -> None:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        # Create futures_orders table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS futures_orders (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id             INTEGER   NOT NULL UNIQUE,
            client_order_id      TEXT,
            symbol               TEXT      NOT NULL,
            status               TEXT      NOT NULL,
            type                 TEXT      NOT NULL,
            side                 TEXT      NOT NULL,
            price                REAL      NOT NULL,
            avg_price            REAL      NOT NULL DEFAULT 0,
            orig_qty             REAL      NOT NULL,
            executed_qty         REAL      NOT NULL,
            cum_quote            REAL      NOT NULL DEFAULT 0,
            time_in_force        TEXT,
            stop_price           REAL      NOT NULL DEFAULT 0,
            iceberg_qty          REAL      NOT NULL DEFAULT 0,
            time                 INTEGER   NOT NULL,
            update_time          INTEGER   NOT NULL,
            is_working           INTEGER   NOT NULL DEFAULT 1,
            position_side        TEXT      DEFAULT 'BOTH',
            reduce_only          INTEGER   NOT NULL DEFAULT 0,
            close_position       INTEGER   NOT NULL DEFAULT 0,
            working_type         TEXT      DEFAULT 'CONTRACT_PRICE',
            price_protect        INTEGER   NOT NULL DEFAULT 0,
            orig_type            TEXT,
            margin_asset         TEXT,
            leverage             INTEGER
        )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_futures_orders_symbol ON futures_orders(symbol)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_futures_orders_time ON futures_orders(time)"
        )
        conn.commit()
        conn.close()

    def create_order(self, data: Dict[str, Any]) -> int:
        """
        Insert a new futures order. Returns the internal row id.
        """
        cols = [
            "order_id", "client_order_id", "symbol", "status", "type", "side",
            "price", "avg_price", "orig_qty", "executed_qty", "cum_quote",
            "time_in_force", "stop_price", "iceberg_qty", "time", "update_time", "is_working",
            "position_side", "reduce_only", "close_position", "working_type",
            "price_protect", "orig_type", "margin_asset", "leverage"
        ]
        placeholders = ", ".join("?" for _ in cols)
        values = [data.get(col) for col in cols]

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            f"INSERT INTO futures_orders ({', '.join(cols)}) VALUES ({placeholders})",
            values
        )
        row_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return row_id

    def get_order(self, order_id: int) -> Optional[Dict[str, Any]]:
        """Fetch a single futures order by Binance order_id."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM futures_orders WHERE order_id = ?", (order_id,)
        )
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        columns = [col[0] for col in cursor.description]
        return dict(zip(columns, row))

    def list_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all futures orders, optionally filtered by symbol."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        if symbol:
            cursor.execute(
                "SELECT * FROM futures_orders WHERE symbol = ? ORDER BY time", (symbol,)
            )
        else:
            cursor.execute("SELECT * FROM futures_orders ORDER BY time")
        rows = cursor.fetchall()
        columns = [col[0] for col in cursor.description]
        conn.close()
        return [dict(zip(columns, row)) for row in rows]

    def update_order(self, order_id: int, updates: Dict[str, Any]) -> None:
        """Update fields of a futures order by Binance order_id."""
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        values = list(updates.values()) + [order_id]

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE futures_orders SET {set_clause} WHERE order_id = ?", values
        )
        conn.commit()
        conn.close()

    def delete_order(self, order_id: int) -> None:
        """Delete a futures order by Binance order_id."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM futures_orders WHERE order_id = ?", (order_id,)
        )
        conn.commit()
        conn.close()
