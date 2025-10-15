import os
import sqlite3
from datetime import datetime

class Logger:
    """
    Simple logger: prints to console in dev, saves to DB in production.
    """
    def __init__(self, env: str = None, db_path: str = "logs.db"):
        self.env = env
        self.db_path = db_path
        if self.env == "production":
            self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS logs (
                timestamp TEXT,
                level TEXT,
                message TEXT
            )
            '''
        )
        conn.commit()
        conn.close()

    def log(self, message: str, level: str = "INFO"):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if self.env == "development":
            print(f"[{ts}] [{level}] {message}")
        else:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO logs (timestamp, level, message) VALUES (?, ?, ?)",
                (ts, level, message)
            )
            conn.commit()
            conn.close()
