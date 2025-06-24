import sqlite3
from typing import Dict

class GridStateDB:
    """
    Handles persistence of grid state using SQLite.
    """
    def __init__(self, db_path: str = "db/grid_state.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS grid_state (
                grid_price REAL PRIMARY KEY,
                filled INTEGER NOT NULL
            )
            '''
        )
        conn.commit()
        conn.close()

    def load_state(self) -> Dict[float, bool]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT grid_price, filled FROM grid_state")
        rows = cursor.fetchall()
        conn.close()
        return {price: bool(filled) for price, filled in rows}

    def save_state(self, state: Dict[float, bool]) -> None:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        for price, filled in state.items():
            cursor.execute(
                'REPLACE INTO grid_state (grid_price, filled) VALUES (?, ?)',
                (price, int(filled))
            )
        conn.commit()
        conn.close()
