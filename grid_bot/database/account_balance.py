import mysql.connector
from datetime import datetime
from typing import Any, Dict, List, Optional

from grid_bot.database.base_database import BaseMySQLRepo


class AccountBalance(BaseMySQLRepo):
    """
    Handles persistence of account balances using Mysql.
    """

    def __init__(self):
        super().__init__()  # initializes connection pool
        self._ensure_table()  # safe place to use DB (open/close)

    def _ensure_table(self):
        conn = self._get_conn()  # use _get_conn(), not super()._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS `account_balance` (
                    `id` INT AUTO_INCREMENT PRIMARY KEY,              -- ไอดีอัตโนมัติ
                    `account_type` VARCHAR(20) DEFAULT NULL,          -- ประเภทบัญชี (SPOT/FUTURES)
                    `symbol` VARCHAR(20) DEFAULT NULL,                -- สัญลักษณ์ (เช่น BTCUSDT)
                    `side` VARCHAR(10) DEFAULT NULL,                  -- ฝั่ง (BUY/SELL/OPEN/CLOSE)
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

            cursor.execute(
                """
                SELECT COUNT(1) FROM INFORMATION_SCHEMA.STATISTICS
                WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = 'account_balance'
                AND INDEX_NAME = 'ux_asset';
            """
            )

            if cursor.fetchone()[0] == 0:
                cursor.execute("CREATE INDEX ux_asset ON account_balance(id, record_date, record_time)")

            conn.commit()
        finally:
            cursor.close()
            conn.close()

    def insert_balance_with_type(self, account_type: str, symbol: str, side: str, balance_usdt: float, available_usdt: float, notes: str = "") -> int:
        """
        Convenience helper to insert a snapshot tagged by account_type (SPOT/FUTURES/COMBINED).
        - start_balance_usdt: total balance
        - end_balance_usdt: available balance
        """
        dt = datetime.now()
        data = {
            "account_type": account_type.upper(),
            "symbol": symbol,
            "side": side.upper(),
            "record_date": dt.strftime("%Y-%m-%d"),
            "record_time": dt.strftime("%H:%M:%S"),
            "start_balance_usdt": balance_usdt,
            "net_flow_usdt": 0.0,
            "realized_pnl_usdt": 0.0,
            "unrealized_pnl_usdt": 0.0,
            "fees_usdt": 0.0,
            "end_balance_usdt": available_usdt,
            "notes": notes,
        }
        return self.insert_balance(data)

    def insert_balance(self, data: Dict[str, Any]) -> int:
        """
        Insert a new Account Balance. Returns the internal row id.
        """
        cols = [
            "account_type",
            "symbol",
            "side",
            "record_date",
            "record_time",
            "start_balance_usdt",
            "net_flow_usdt",
            "realized_pnl_usdt",
            "unrealized_pnl_usdt",
            "fees_usdt",
            "end_balance_usdt",
            "notes",
        ]

        placeholders = ", ".join(["%s" for _ in cols])  # ✅ MySQL ใช้ %s
        values = [data.get(col) for col in cols]

        conn = self._get_conn()
        cursor = conn.cursor()
        sql = f"INSERT INTO account_balance ({', '.join(cols)}) VALUES ({placeholders})"

        try:
            cursor.execute(sql, values)
            row_id = cursor.lastrowid
            conn.commit()
            return row_id
        finally:
            cursor.close()
            conn.close()

    def delete_balance(self, record_id: int) -> None:
        """
        Deletes an account balance record by its ID.
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM account_balance WHERE id = %s", (record_id,))
            conn.commit()
        finally:
            cursor.close()
            conn.close()

    def delete_balances_older_than(self, cutoff_date: str) -> None:
        """
        Deletes account balance records older than the specified date.
        :param cutoff_date: Date in 'YYYY-MM-DD' format
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM account_balance WHERE record_date < %s", (cutoff_date,))
            conn.commit()
        finally:
            cursor.close()
            conn.close()

    def delete_all_balances(self) -> None:
        """
        Deletes all account balance records.
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM account_balance")
            conn.commit()
        finally:
            cursor.close()
            conn.close()

    def drop_table(self) -> None:
        """
        Drops the account_balance table. Use with caution.
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute("DROP TABLE IF EXISTS account_balance")
            conn.commit()
        finally:
            cursor.close()
            conn.close()

    def get_latest_balance_by_type(self, account_type: str, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Fetch latest balance row filtered by account_type in notes.
        """
        conn = self._get_conn()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT * FROM account_balance
                 WHERE account_type = %s
                 AND symbol = %s
                 ORDER BY id DESC
                 LIMIT 1
                """,
                (f"{account_type.upper()}", f"{symbol}"),
            )
            row = cursor.fetchone()
            return row
        finally:
            cursor.close()
            conn.close()
