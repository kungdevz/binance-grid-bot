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
        raise NotImplementedError
