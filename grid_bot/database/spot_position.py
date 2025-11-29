import mysql.connector
from typing import Any, Dict, Optional, List
from grid_bot.database.base_database import BaseMySQLRepo


class SpotPosition(BaseMySQLRepo):
    def __init__(self) -> None:
        super().__init__()
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS spot_positions (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    env VARCHAR(16) NOT NULL,
                    symbol VARCHAR(32) NOT NULL,
                    side VARCHAR(8) NOT NULL,
                    status VARCHAR(16) NOT NULL,
                    entry_price DECIMAL(18,8) NOT NULL,
                    qty_opened DECIMAL(18,8) NOT NULL,
                    qty_open DECIMAL(18,8) NOT NULL,
                    grid_price DECIMAL(18,8) NOT NULL,
                    target_price DECIMAL(18,8) NOT NULL,
                    closed_price DECIMAL(18,8),
                    opened_at_ms BIGINT NOT NULL,
                    closed_at_ms BIGINT,
                    grid_group_id VARCHAR(64),
                    spot_open_order_id BIGINT,
                    spot_close_order_id BIGINT,
                    spot_open_order_row_id BIGINT,
                    spot_close_order_row_id BIGINT,
                    realized_pnl_usdt DECIMAL(18,8) NOT NULL DEFAULT 0,
                    fee_open_usdt DECIMAL(18,8) NOT NULL DEFAULT 0,
                    fee_close_usdt DECIMAL(18,8) NOT NULL DEFAULT 0,
                    hedged TINYINT(1) NOT NULL DEFAULT 0,
                    meta_json TEXT,

                    INDEX idx_spot_position_group_id (grid_group_id, grid_price, symbol)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """
            )
            conn.commit()
        finally:
            cursor.close()
            conn.close()

    def create_position(self, data: Dict[str, Any]) -> int:
        # insert แล้วคืน id
        ...

    def close_position(self, position_id: int, data: Dict[str, Any]) -> None:
        # update status, closed_at_ms, closed_price, realized_pnl_usdt, fee_close_usdt
        ...

    def update_qty(self, position_id: int, qty_open: float) -> None: ...

    def get_open_positions(self, env: str, symbol: str) -> List[Dict[str, Any]]: ...
