import mysql.connector
from typing import Dict, Any, Optional, List

from grid_bot.database.base_database import BaseMySQLRepo


class AccountBalance(BaseMySQLRepo):
    """
    Handles persistence of account balances using SQLite.
    """

    def __init__(self):
        super().__init__()       # ✅ initializes connection pool
        self._ensure_table()     # safe place to use DB (open/close)
    
    def _ensure_table(self):
        conn = self._get_conn()  # ✅ use _get_conn(), not super()._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS `account_balance` (
                `id` INT AUTO_INCREMENT PRIMARY KEY,              -- ไอดีอัตโนมัติ
                `record_date` DATE NOT NULL,                      -- วันที่บันทึก (YYYY-MM-DD)
                `record_time` TIME NOT NULL,                      -- เวลาบันทึก (HH:MM:SS)
                `start_balance_usdt` DECIMAL(18,6) NOT NULL,      -- ยอดเงินเริ่มต้น (USDT)
                `net_flow_usdt` DECIMAL(18,6) DEFAULT 0,          -- ฝาก–ถอนสุทธิ (USDT)
                `realized_pnl_usdt` DECIMAL(18,6) DEFAULT 0,      -- กำไร/ขาดทุนที่ปิดแล้ว (USDT)
                `unrealized_pnl_usdt` DECIMAL(18,6) DEFAULT 0,    -- กำไร/ขาดทุนที่ลอยตัว (USDT)
                `fees_usdt` DECIMAL(18,6) DEFAULT 0,              -- ค่าธรรมเนียมทั้งหมด (USDT)
                `end_balance_usdt` DECIMAL(18,6) NOT NULL,        -- ยอดเงินสุดท้าย (USDT)
                `notes` TEXT                                      -- หมายเหตุ (เช่น เปิด/ปิด hedge, ปรับ grid spacing)
            )
            """
        )

        cursor.execute("""
            SELECT COUNT(1) FROM INFORMATION_SCHEMA.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
            AND TABLE_NAME = 'account_balance'
            AND INDEX_NAME = 'ux_asset';
        """)
        
        if cursor.fetchone()[0] == 0:
            cursor.execute("CREATE INDEX ux_asset ON account_balance(id, record_date, record_time)")

        conn.commit()
        cursor.close()
        conn.close()

    def insert_balance(self, data: Dict[str, Any]) -> int:
        """
        Insert a new Account Balance. Returns the internal row id.
        """
        cols = [
            "record_date", "record_time", "start_balance_usdt", "net_flow_usdt", "realized_pnl_usdt",
            "unrealized_pnl_usdt", "fees_usdt", "end_balance_usdt", "notes"
        ]

        placeholders = ", ".join(["%s" for _ in cols])  # ✅ MySQL ใช้ %s
        values = [data.get(col) for col in cols]

        conn = self._get_conn()
        cursor = conn.cursor()
        sql = f"INSERT INTO account_balance ({', '.join(cols)}) VALUES ({placeholders})"

        cursor.execute(sql, values)
        row_id = cursor.lastrowid
        conn.commit()
        cursor.close()
        conn.close()
        return row_id
    
    def delete_balance(self, record_id: int) -> None:
        """
        Deletes an account balance record by its ID.
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM account_balance WHERE id = ?",
            (record_id,)
        )
        conn.commit()
        cursor.close()
        conn.close()
    
    def delete_balances_older_than(self, cutoff_date: str) -> None:
        """
        Deletes account balance records older than the specified date.
        :param cutoff_date: Date in 'YYYY-MM-DD' format
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM account_balance WHERE record_date < ?",
            (cutoff_date,)
        )
        conn.commit()
        cursor.close()
        conn.close()
    
    def delete_all_balances(self) -> None:
        """
        Deletes all account balance records.
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM account_balance")
        conn.commit()
        cursor.close()
        conn.close()
    
    def drop_table(self) -> None:
        """
        Drops the account_balance table. Use with caution.
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("DROP TABLE IF EXISTS account_balance")
        conn.commit()
        cursor.close()
        conn.close()