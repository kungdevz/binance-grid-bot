import sqlite3
from typing import Dict, Any, Optional, List

class AccountBalanceDB:
    """
    Handles persistence of account balances using SQLite.
    """

    def __init__(self, db_path: str = "database/schema/backtest_bot.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Create table for account balances
        cursor.execute(
            """
            CREATE TABLE account_balance (
                id                      INTEGER     PRIMARY KEY AUTOINCREMENT,  -- ไอดีอัตโนมัติ
                record_date             DATE        NOT NULL,                  -- วันที่บันทึก (YYYY-MM-DD)
                record_time             TIME        NOT NULL,                  -- เวลาบันทึก (HH:MM:SS)
                start_balance_usdt      REAL        NOT NULL,                  -- ยอดเงินเริ่มต้น (USDT)
                net_flow_usdt           REAL        DEFAULT 0,                 -- ฝาก–ถอนสุทธิ (USDT)
                realized_pnl_usdt       REAL        DEFAULT 0,                 -- กำไร/ขาดทุนที่ปิดแล้ว (USDT)
                unrealized_pnl_usdt     REAL        DEFAULT 0,                 -- กำไร/ขาดทุนที่ลอยตัว (USDT)
                fees_usdt               REAL        DEFAULT 0,                 -- ค่าธรรมเนียมทั้งหมด (USDT)
                end_balance_usdt        REAL        NOT NULL,                  -- ยอดเงินสุดท้าย (USDT)
                notes                   TEXT                                   -- หมายเหตุ (เช่น เปิด/ปิด hedge, ปรับ grid spacing)
            )
            """
        )

        cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_asset ON account_balance(id, record_date, record_time);
            """
        )

        conn.commit()
        conn.close()