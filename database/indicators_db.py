import sqlite3
from typing import Optional, List, Dict, Any
import pandas as pd

class IndicatorsDatabase:

    def __init__(self, db_path: str = 'database/schema/backtest_bot.db'):
        self.db_path = db_path
        self.create_ohlcv_table()

    def create_ohlcv_table(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ohlcv_data (
                symbol      TEXT    NOT NULL,
                timestamp   INTEGER NOT NULL,
                open        REAL    NOT NULL,
                high        REAL    NOT NULL,
                low         REAL    NOT NULL,
                close       REAL    NOT NULL,
                volume      REAL    NOT NULL,
                tr          REAL    NOT NULL,
                atr_14      REAL    NOT NULL,
                atr_28      REAL    NOT NULL,
                ema_14      REAL    NOT NULL,
                ema_28      REAL    NOT NULL,
                ema_50      REAL    NOT NULL,
                ema_100     REAL    NOT NULL,
                ema_200     REAL    NOT NULL,
                PRIMARY KEY(symbol, timestamp)
            )
        ''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ohlcv_data ON spot_orders(timestamp, symbol)")

        conn.commit()
        conn.close()

    def insert_ohlcv_data(
        self,
        symbol: str,
        timestamp: int,
        open: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        tr: float,
        atr: float,
        ema_14: float,
        ema_28: float,
        ema_50: float,
        ema_100: float,
        ema_200: float
    ):
        """
        บันทึกข้อมูล OHLCV พร้อม indicators ลงฐานข้อมูล
        """
        insert_sql = '''
        INSERT OR REPLACE INTO ohlcv_data(
            symbol, timestamp, open, high, low, close, volume,
            tr, atr, ema_14, ema_28, ema_50, ema_100, ema_200
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        '''
        self.conn.execute(
            insert_sql,
            (symbol, timestamp, open, high, low, close, volume,
             tr, atr, ema_14, ema_28, ema_50, ema_100, ema_200)
        )
        self.conn.commit()

    def get_recent_ohlcv(self, symbol: str, limit: int) -> pd.DataFrame:
        """
        ดึง OHLCV พร้อม ATR/EMA ล่าสุดตามจำนวน limit เพื่อนำมาคำนวณ indicators
        """
        query = '''
        SELECT timestamp, open, high, low, close, volume, tr, atr
               ema_14, ema_28, ema_50, ema_100, ema_200
        FROM ohlcv_data
        WHERE symbol = ?
        ORDER BY timestamp DESC
        LIMIT ?
        '''
        df = pd.read_sql_query(query, self.conn, params=(symbol, limit))
        # คืนค่า DataFrame เรียง timestamp จากเก่า->ใหม่
        return df.iloc[::-1].reset_index(drop=True)
