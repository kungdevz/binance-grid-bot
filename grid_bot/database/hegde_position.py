from typing import Any, Dict, List, Optional
from grid_bot.database.base_database import BaseMySQLRepo


class HedgePosition(BaseMySQLRepo):
    def __init__(self) -> None:
        super().__init__()
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS hedge_positions (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    env          VARCHAR(16) NOT NULL,   -- 'backtest', 'live'
                    symbol       VARCHAR(32) NOT NULL,   -- futures symbol, เช่น 'XRPUSDT'
                    side         VARCHAR(8)  NOT NULL,   -- 'SHORT'
                    status       VARCHAR(16) NOT NULL,   -- 'OPEN', 'CLOSED', 'PARTIAL'
                    entry_price  DECIMAL(18,8) NOT NULL,
                    qty          DECIMAL(18,8) NOT NULL,
                    leverage     INT NOT NULL,
                    opened_at_ms BIGINT NOT NULL,
                    closed_at_ms BIGINT NULL,
                    reason_open  VARCHAR(32) NULL,       -- 'DANGER_ZONE', 'SL_RECENTER', ...
                    reason_close VARCHAR(32) NULL,       -- 'RECENTER', 'TP', 'STOP_OUT'
                    grid_group_id VARCHAR(64) NULL,      -- group ของ grid ตอนที่เปิด hedge
                    futures_open_order_id  BIGINT NULL,
                    futures_close_order_id BIGINT NULL,
                    futures_open_order_row_id  BIGINT NULL,
                    futures_close_order_row_id BIGINT NULL,
                    realized_pnl_usdt DECIMAL(18,8) NOT NULL DEFAULT 0,
                    fee_open_usdt     DECIMAL(18,8) NOT NULL DEFAULT 0,
                    fee_close_usdt    DECIMAL(18,8) NOT NULL DEFAULT 0,
                    meta_json TEXT NULL
                )   ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """
            )
            conn.commit()
        finally:
            cursor.close()
            conn.close()

    def create_position(self, data: Dict[str, Any]) -> int: ...
    def close_position(self, position_id: int, data: Dict[str, Any]) -> None: ...
    def get_last_open(self, env: str, symbol: str) -> Optional[Dict[str, Any]]: ...
