import mysql.connector
from typing import Optional, List, Dict, Any
import pandas as pd

from grid_bot.database.base_database import BaseMySQLRepo

class OhlcvData(BaseMySQLRepo):

    def __init__(self):
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ohlcv_data (
                symbol        VARCHAR(20)   NOT NULL,
                timestamp     BIGINT        NOT NULL,
                open_price    DOUBLE        NOT NULL,
                high_price    DOUBLE        NOT NULL,
                low_price     DOUBLE        NOT NULL,
                close_price   DOUBLE        NOT NULL,
                volume        DOUBLE        NOT NULL,
                tr            DOUBLE        NOT NULL,
                atr_14        DOUBLE        NOT NULL,
                atr_28        DOUBLE        NOT NULL,
                ema_14        DOUBLE        NOT NULL,
                ema_28        DOUBLE        NOT NULL,
                ema_50        DOUBLE        NOT NULL,
                ema_100       DOUBLE        NOT NULL,
                ema_200       DOUBLE        NOT NULL,
                PRIMARY KEY (symbol, timestamp)
            )
        ''')

        cursor.execute("""
            SELECT COUNT(1) FROM INFORMATION_SCHEMA.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
            AND TABLE_NAME = 'ohlcv_data'
            AND INDEX_NAME = 'idx_ohlcv_data';
        """)
        
        if cursor.fetchone()[0] == 0:
            cursor.execute("CREATE INDEX idx_ohlcv_data ON ohlcv_data(timestamp, symbol)")
        
        conn.commit()
        cursor.close()
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
        conn = self._get_conn()
        cursor = conn.cursor()

        insert_sql = '''
            INSERT OR REPLACE INTO ohlcv_data(
                symbol, timestamp, open, high, low, close, volume,
                tr, atr, ema_14, ema_28, ema_50, ema_100, ema_200
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            '''
        cursor.execute(
            insert_sql,
            (symbol, timestamp, open, high, low, close, volume,
             tr, atr, ema_14, ema_28, ema_50, ema_100, ema_200)
        )

        conn.commit()
        cursor.close()
        conn.close()

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
