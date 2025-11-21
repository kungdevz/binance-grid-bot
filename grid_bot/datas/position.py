from dataclasses import dataclass, field
from typing import Any, Dict

@dataclass
class Position:
    symbol: str
    side: str        # "LONG" (spot buy)
    entry_price: float
    qty: float
    grid_price: float       # level ที่ใช้เปิด order
    target_price: float     # ราคา TP
    opened_at: int          # timestamp ms
    group_id: str
    hedged: bool = False    # ใช้กับ hedge logic
    meta: Dict[str, Any] = field(default_factory=dict)

