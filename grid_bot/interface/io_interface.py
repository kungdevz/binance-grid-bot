# ------------------------------------------------------------------
# Abstract “I/O” methods – ให้ subclass ไป implement
# ------------------------------------------------------------------
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from grid_bot.datas.position import Position


class IGridIO(ABC):
    """
    Abstract I/O methods for grid bot.
    Subclasses must implement these methods for live or backtest functionality.
    """

    @property
    def is_paper_mode(self) -> bool:
        """
        ใช้เช็คว่า strategy ตอนนี้อยู่ใน mode backtest/forward_test (paper trade)
        """
        return self.mode in ("backtest", "forward_test")

    @abstractmethod
    def _io_place_spot_buy(self, timestamp_ms: int, price: float, qty: float, grid_id: str) -> Dict[str, Any]:
        """
        ให้ subclass live/backtest ไป implement:
        - live: เรียก ExchangeSync.place_limit_buy + เขียน DB
        - backtest: จำลอง fill ทันที + เขียน DB (ถ้าต้องการ)
        return: ข้อมูล order ที่อยากเก็บ (order_id ฯลฯ)
        """
        raise NotImplementedError

    @abstractmethod
    def _io_place_spot_sell(self, timestamp_ms: int, position: Position, sell_price: float) -> Dict[str, Any]:
        """
        ให้ subclass ไป implement:
        - live: ยิง sell ไปที่ exchange (limit/market แล้วแต่ design)
        - backtest: จำลอง fill ทันที
        """
        raise NotImplementedError

    @abstractmethod
    def _io_open_hedge_short(self, timestamp_ms: int, qty: float, price: float, reason: str) -> Optional[float]:
        """
        เปิด short futures จริง (live) หรือ mock (backtest)
        return: entry_price ถ้าสำเร็จ, None ถ้า fail
        """
        raise NotImplementedError

    @abstractmethod
    def _io_close_hedge(self, timestamp_ms: int, qty: float, price: float, reason: str) -> None:
        """
        ปิด short futures จริง (live) หรือ mock (backtest)
        """
        raise NotImplementedError

    @abstractmethod
    def _run(self, timestamp_ms: int) -> None:
        """
        main loop I/O operation per timestamp
        """
        raise NotImplementedError

    @abstractmethod
    def _io_refresh_balances(self) -> None:
        """
        ใช้ refresh available_capital (spot) และ futures_available_margin (futures)
        - backtest/forward: จาก DB
        - live: จาก exchange
        """
        raise NotImplementedError

    @abstractmethod
    def _after_grid_sell(
        self,
        timestamp_ms: int,
        pos: Position,
        sell_price: float,
        notional: float,
        fee: float,
        pnl: float,
    ) -> None:
        """
        เรียกหลังจาก _io_place_spot_sell เสร็จและคำนวณ notional/pnl แล้ว
        - Base class: no-op
        - BacktestGridStrategy / LiveGridStrategy จะ override เพื่อทำ accounting/logging
        """
        raise NotImplementedError

    @abstractmethod
    def _after_grid_buy(
        self,
        timestamp_ms: int,
        grid_price: float,
        buy_price: float,
        qty: float,
        notional: float,
        fee: float,
    ) -> None:
        """
        Called หลังจาก Grid BUY ถูก fill และสร้าง Position แล้ว
        - Base: no-op
        - BacktestGridStrategy: จะหัก available_capital และ snapshot
        - LiveGridStrategy: ส่วนใหญ่จะไม่ทำอะไร (ปล่อยให้ exchange เป็น source of truth)
        """
        raise NotImplementedError

    @abstractmethod
    def _snapshot_account_balance(
        self,
        timestamp_ms: int,
        current_price: float,
        side: str,
        notes: str = "",
    ) -> None:
        """
        Backtest เท่านั้น default base ไม่ทำอะไร
        Subclass (BacktestGridStrategy) จะ override ให้ไปเขียนลง DB
        """
        raise NotImplementedError

    @abstractmethod
    def _record_hedge_balance(
        self,
        timestamp_ms: int,
        current_price: float,
        notes: str,
    ) -> None:
        """
        Default: no-op. BacktestGridStrategy/LiveGridStrategy เลือก override ได้เอง
        """
        raise NotImplementedError
