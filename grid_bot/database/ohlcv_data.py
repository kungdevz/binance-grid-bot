from typing import Optional, List, Dict, Any

from grid_bot.database.base_database import BaseMySQLRepo

class OhlcvData(BaseMySQLRepo):

    def __init__(self):
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
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
        """)

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

    def insert_ohlcv_data(self,data: dict) -> int:

        try:

            conn = self._get_conn()
            cursor = conn.cursor()

            insert_sql = '''
                INSERT INTO ohlcv_data(
                    symbol, timestamp, open_price, high_price, low_price, close_price, volume,
                    tr, atr_14, atr_28, ema_14, ema_28, ema_50, ema_100, ema_200
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            '''

            cursor.execute(insert_sql, (
                data["symbol"], data["timestamp"], data["open_price"], data["high_price"],
                data["low_price"], data["close_price"], data["volume"], data["tr"],
                data["atr_14"], data["atr_28"], data["ema_14"], data["ema_28"],
                data["ema_50"], data["ema_100"], data["ema_200"]
            ))

            conn.commit()
            return cursor.rowcount
    
        finally:
            cursor.close() 
            conn.close()

    def delete_ohlcv_data(self, symbol: str, timestamp: int) -> int:
        conn = self._get_conn()
        cursor = conn.cursor()

        delete_sql = 'DELETE FROM ohlcv_data WHERE symbol = %s AND timestamp = %s'
        cursor.execute(delete_sql, (symbol, timestamp))

        affected_rows = cursor.rowcount
        conn.commit()

        cursor.close()
        conn.close()

        return affected_rows
    
    def delete_ohlcv_older_than(self, symbol: str, timestamp: int) -> int:
        conn = self._get_conn()
        cursor = conn.cursor()

        delete_sql = 'DELETE FROM ohlcv_data WHERE symbol = %s AND timestamp < %s'
        cursor.execute(delete_sql, (symbol, timestamp))

        affected_rows = cursor.rowcount
        conn.commit()

        cursor.close()
        conn.close()

        return affected_rows
    
    def delete_ohlcv_by_symbol(self, symbol: str) -> int:
        conn = self._get_conn()
        cursor = conn.cursor()

        delete_sql = 'DELETE FROM ohlcv_data WHERE symbol = %s'
        cursor.execute(delete_sql, (symbol,))

        affected_rows = cursor.rowcount
        conn.commit()

        cursor.close()
        conn.close()

        return affected_rows
    
    def get_recent_ohlcv_by_timestamp(self, symbol: str, timestamp: int, limit: int) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        cursor = conn.cursor()
        query = '''
            SELECT symbol, timestamp, open_price, high_price, low_price, close_price, volume, 
                tr, atr_14, atr_28, ema_14, ema_28, ema_50, ema_100, ema_200
            FROM ohlcv_data
            WHERE symbol = %s AND timestamp <= %s
            ORDER BY timestamp DESC
            LIMIT %s
        '''
        try:   
            cursor.execute(query, (symbol, timestamp, limit))
            rows = cursor.fetchall()    
            return rows
        finally:
            cursor.close()
            conn.close()

    def get_recent_ohlcv(self, symbol: str, limit: int) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        cursor = conn.cursor(dictionary=True)

        query = '''
            SELECT timestamp, open_price, high_price, low_price, 
                close_price, volume, tr, atr_14, atr_28, ema_14, 
                ema_28, ema_50, ema_100, ema_200
            FROM ohlcv_data
            WHERE symbol = %s
            ORDER BY timestamp DESC
            LIMIT %s
        '''

        try:
            cursor.execute(
                query, (symbol, limit)
            )
            rows = cursor.fetchall()
            return rows
        finally:
            cursor.close()
            conn.close()
