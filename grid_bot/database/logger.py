import os
import mysql.connector
from datetime import datetime
from grid_bot.database.base_database import BaseMySQLRepo

class Logger(BaseMySQLRepo):
    """
    Simple logger: prints to console in dev, saves to DB in production.
    """
    def __init__(self):
        super().__init__()       # initializes connection pool
        self._ensure_table()     # safe place to use DB (open/close)
        self.env = os.getenv("ENVIRONMENT", "development")
    
    def _ensure_table(self):
        conn = self._get_conn()  # ✅ use _get_conn(), not super()._get_conn()
        cursor = conn.cursor()
        try:
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
        finally:
            cursor.close()
            conn.close()

       

    def log(self, message: str, level: str = "INFO", env: str = None):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if self.env == "development":
            print(f"[{ts}] [{level}] {message}")
        else:
            conn = self._get_conn()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "INSERT INTO logs (timestamp, level, message) VALUES (%s, %s, %s)", (ts, level, message)
                )
                conn.commit()
            finally:
                cursor.close()
                conn.close()
