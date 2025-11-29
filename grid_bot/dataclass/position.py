from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class Position:
    symbol: str
    side: str  # "LONG" (spot buy)
    entry_price: float
    qty: float
    grid_price: float
    target_price: float
    opened_at: int
    group_id: str
    hedged: bool = False
    meta: Dict[str, Any] = field(default_factory=dict)

    # เชื่อมกับ DB / Exchange
    db_id: int | None = None  # primary key ใน spot_positions
    open_order_id: int | None = None  # Binance spot orderId
    close_order_id: int | None = None
    open_order_row_id: int | None = None  # row id ใน spot_orders (ถ้ามี)
    close_order_row_id: int | None = None
