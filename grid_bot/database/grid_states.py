import mysql.connector
from typing import Dict, List, Any
from grid_bot.database.base_database import BaseMySQLRepo

class GridState(BaseMySQLRepo):
    """
    Handles persistence of grid state using SQLite, with statuses and timestamps.
    """

    def __init__(self):
        conn = self._get_conn()
        cursor = conn.cursor()
        # Create table without 'filled' column
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS `grid_state` (
                `id` INT AUTO_INCREMENT PRIMARY KEY,               -- เพิ่ม id สำหรับ primary key
                `grid_price` DECIMAL(18,8) NOT NULL,               -- ราคาของ grid
                `use_status` VARCHAR(1) NOT NULL DEFAULT 'N',      -- สถานะใช้งาน (Y/N)
                `groud_id` VARCHAR(64) NOT NULL,                   -- กลุ่มคำสั่ง
                `date` DATE DEFAULT (CURRENT_DATE),                -- วันที่บันทึก (YYYY-MM-DD)
                `time` TIME DEFAULT NULL,                          -- เวลาบันทึก (HH:MM:SS)
                `base_price` DECIMAL(18,8) NOT NULL DEFAULT 0.0,   -- ราคาฐาน
                `spacing` DECIMAL(18,8) NOT NULL DEFAULT 0.0,      -- ระยะห่างระหว่าง grid
                `create_date` DATETIME DEFAULT CURRENT_TIMESTAMP,  -- วันที่สร้าง
                `update_date` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP -- วันที่อัปเดต
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
            cursor.execute("CREATE INDEX ux_grid_group_price ON grid_state(groud_id, grid_price)")

        conn.commit()
        conn.close()

    def load_state_with_use_flgs(self, use_flgs : str = 'Y') -> List[Dict[str, Any]]:
        """
        Load grid entries that are not cancelled.
        Returns a dict mapping price to its status ('Y' or 'N').
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM grid_state WHERE use_status = ? ORDER BY grid_price ASC", (use_flgs)
        )
        rows = cursor.fetchall()
        conn.close()
        columns = [col[0] for col in cursor.description]
        conn.close()
        return [dict(zip(columns, row)) for row in rows]

    def save_state(self, entry: dict) -> int:
        """
        Upsert grid entries:
        - New entries are inserted with status as given.
        - Existing entries have their status and update_date updated.
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
                INSERT INTO grid_state (grid_price, use_status, groud_id, base_price, spacing, date, time, create_date)
                    VALUES (:grid_price, :use_status, :groud_id, :base_price, :spacing, :date, :time, :create_date)
                    ON CONFLICT(groud_id, grid_price) DO UPDATE SET
                        use_status   = excluded.use_status,
                        base_price   = excluded.base_price,
                        spacing      = excluded.spacing,
                        date         = excluded.date,
                        time         = excluded.time,
                        create_date  = excluded.create_date
            """,
            entry
        )
        conn.commit()
        conn.close()
        return cursor.lastrowid

    def mark_filled(self, price: float) -> int:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE grid_state
               SET status      = 'close',
                   update_date = CURRENT_TIMESTAMP
             WHERE grid_price = ?
            """, (price)
        )
        conn.commit()
        conn.close()
        return cursor.rowid

    def mark_open(self, price: float) -> int:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE grid_state
               SET status      = 'open',
                   update_date = CURRENT_TIMESTAMP
             WHERE grid_price = ?
            """, (price)
        )
        conn.commit()
        conn.close()
        return cursor.rowid

    def cancel_all_open(self) -> int:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE grid_state
               SET status      = 'cancelled',
                   update_date = CURRENT_TIMESTAMP
             WHERE status = 'open'
            """
        )
        conn.commit()
        conn.close()
