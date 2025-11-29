from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class HedgePosition:
    symbol: str
    side: str  # 'SHORT'
    entry_price: float
    qty: float
    leverage: int
    opened_at: int
    group_id: str
    status: str = "OPEN"
    meta: Dict[str, Any] = field(default_factory=dict)
    db_id: int | None = None
    open_order_id: int | None = None
    close_order_id: int | None = None
