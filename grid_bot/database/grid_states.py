from typing import Dict, List, Any
from grid_bot.database.base_database import BaseMySQLRepo

class GridState(BaseMySQLRepo):
    """
    Handles persistence of grid state using Mysql, with statuses and timestamps.
    """

    def __init__(self):
        conn = self._get_conn()
        cursor = conn.cursor()
        # Create table without 'filled' column
        try:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS `grid_state` (
                    `id` INT AUTO_INCREMENT PRIMARY KEY,
                    `symbol` varchar(255) NOT NULL,
                    `grid_price` decimal(18, 8) NOT NULL,
                    `use_status` varchar(1) NOT NULL DEFAULT 'N',
                    `group_id` varchar(64) NOT NULL,
                    `date` date DEFAULT(curdate()),
                    `time` time DEFAULT NULL,
                    `base_price` decimal(18, 8) NOT NULL DEFAULT '0.00000000',
                    `spacing` decimal(18, 8) NOT NULL DEFAULT '0.00000000',
                    `create_date` datetime DEFAULT CURRENT_TIMESTAMP,
                    `update_date` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP            
                )
                """
            )

            cursor.execute("""
                SELECT COUNT(1) FROM INFORMATION_SCHEMA.STATISTICS
                WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = 'grid_state'
                AND INDEX_NAME = 'ux_grid_group_price';
            """)
            
            if cursor.fetchone()[0] == 0:
                cursor.execute("CREATE INDEX ux_grid_group_price ON grid_state(group_id, grid_price)")

        finally:
            conn.commit()
            conn.close()

    def load_state_with_use_flgs(self, symbol,  use_flgs: str = "Y") -> List[Dict[str, Any]]:
        conn = self._get_conn()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                "SELECT * FROM grid_state WHERE symbol = %s and use_status = %s ORDER BY grid_price ASC",
                (symbol, use_flgs),
            )
            rows = cursor.fetchall()
            return rows
        finally:
            cursor.close()
            conn.close()

    def save_state(self, entry: dict) -> int:
        """
        Upsert grid entries:
        - New entries are inserted with status as given.
        - Existing entries have their status and update_date updated.
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                    INSERT INTO grid_state (
                        symbol,
                        grid_price,
                        use_status,
                        group_id,
                        base_price,
                        spacing,
                        date,
                        time,
                        create_date
                    ) VALUES ( %(symbol)s, %(grid_price)s, %(use_status)s, %(group_id)s, %(base_price)s, %(spacing)s, %(date)s, %(time)s, %(create_date)s )
                    ON DUPLICATE KEY UPDATE
                        symbol       = VALUES(symbol),
                        use_status   = VALUES(use_status),
                        base_price   = VALUES(base_price),
                        spacing      = VALUES(spacing),
                        date         = VALUES(date),
                        time         = VALUES(time),
                        group_id     = VALUES(group_id),
                        create_date  = VALUES(create_date);
                """,
                entry
            )

            id = cursor.lastrowid
            conn.commit()
            return id
        finally:
            cursor.close()
            conn.close()
        

    def mark_filled(self, price: float) -> int:
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE grid_state
                   SET status      = 'close',
                       update_date = CURRENT_TIMESTAMP
                 WHERE grid_price = %s
                """,
                (price,),
            )
            conn.commit()
            return cursor.rowcount
        finally:
            cursor.close()
            conn.close()

        

    def mark_open(self, price: float) -> int:
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE grid_state
                   SET status      = 'open',
                       update_date = CURRENT_TIMESTAMP
                 WHERE grid_price = %s
                """,
                (price,),
            )
            conn.commit()
            return cursor.rowcount
        finally:
            cursor.close()
            conn.close()


    def cancel_all_open(self) -> int:
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE grid_state
                   SET status      = 'cancelled',
                       update_date = CURRENT_TIMESTAMP
                 WHERE status = 'open'
                """
            )
            conn.commit()
            return cursor.rowcount
        finally:
            cursor.close()
            conn.close()


    def delete_all_states(self) -> int:
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM grid_state")
            conn.commit()
            return cursor.rowcount
        finally:
            cursor.close()
            conn.close()

    def deactivate_group(self, symbol: str, group_id: str, reason: str = "RECENTER") -> int:
        """
        Mark all rows of a grid group as inactive (use_status='N').
        Schema has no reason column, so `reason` is informational only.
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE grid_state
                   SET use_status = 'N',
                       update_date = CURRENT_TIMESTAMP
                 WHERE symbol = %s AND group_id = %s
                """,
                (symbol, group_id),
            )
            conn.commit()
            return cursor.rowcount
        finally:
            cursor.close()
            conn.close()
