# db.py

import sqlite3
from typing import Dict

class GridStateDB:
    """
    Handles persistence of grid state using SQLite, with statuses and timestamps.
    """

    def __init__(self, db_path: str = "db/backtest_bot.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Create table without 'filled' column
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS grid_state (
                grid_price   REAL      PRIMARY KEY,
                status       TEXT      NOT NULL DEFAULT 'open',
                create_date  DATETIME  NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                update_date  DATETIME  NOT NULL DEFAULT (CURRENT_TIMESTAMP)
            )
            """
        )

        conn.commit()
        conn.close()

    def load_state(self) -> Dict[float, str]:
        """
        Load grid entries that are not cancelled.
        Returns a dict mapping price to its status ('open' or 'filled').
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT grid_price, status FROM grid_state WHERE status!='cancelled'"
        )
        rows = cursor.fetchall()
        conn.close()
        return {price: status for price, status in rows}

    def save_state(self, state: Dict[float, str]) -> None:
        """
        Upsert grid entries:
        - New entries are inserted with status as given.
        - Existing entries have their status and update_date updated.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        for price, status in state.items():
            cursor.execute(
                """
                INSERT INTO grid_state (grid_price, status)
                VALUES (?, ?)
                ON CONFLICT(grid_price) DO UPDATE
                  SET status      = 'open',
                      update_date = CURRENT_TIMESTAMP
                """,
                (price, status)
            )
        conn.commit()
        conn.close()

    def mark_filled(self, price: float) -> None:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE grid_state
               SET status      = 'filled',
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
