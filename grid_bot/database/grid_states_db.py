import sqlite3
from typing import Dict, List, Any

class GridStateDB:
    """
    Handles persistence of grid state using SQLite, with statuses and timestamps.
    """

    def __init__(self, db_path: str = "database/schema/backtest_bot.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Create table without 'filled' column
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS grid_state (
                grid_price    REAL      NOT NULL,
                use_status    TEXT      NOT NULL DEFAULT 'N',
                groud_id      TEXT      NOT NULL,
                date          DATE      NULL DEFAULT CURRENT_DATE,  -- วันที่บันทึก (YYYY-MM-DD)
                time          INTEGER   NULL,                       -- เวลาบันทึก (HH:MM:SS)
                base_price    REAL      NOT NULL DEFAULT 0.0,
                spacing       REAL      NOT NULL DEFAULT 0.0,
                create_date   DATETIME  NULL DEFAULT CURRENT_TIMESTAMP,
                update_date   DATETIME  NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_grid_group_price ON grid_state(groud_id, grid_price);
            """
        )

        conn.commit()
        conn.close()

    def load_state_with_use_flgs(self, use_flgs : str = 'Y') -> List[Dict[str, Any]]:
        """
        Load grid entries that are not cancelled.
        Returns a dict mapping price to its status ('Y' or 'N').
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM grid_state WHERE use_status = ? ORDER BY grid_price ASC", (use_flgs)
        )
        rows = cursor.fetchall()
        conn.close()
        columns = [col[0] for col in cursor.description]
        conn.close()
        return [dict(zip(columns, row)) for row in rows]

    def save_state(self, entry: dict) -> None:
        """
        Upsert grid entries:
        - New entries are inserted with status as given.
        - Existing entries have their status and update_date updated.
        """
        conn = sqlite3.connect(self.db_path)
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

    def mark_filled(self, price: float) -> None:
        conn = sqlite3.connect(self.db_path)
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

    def mark_open(self, price: float) -> None:
        conn = sqlite3.connect(self.db_path)
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

    def cancel_open(self) -> None:
        conn = sqlite3.connect(self.db_path)
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
