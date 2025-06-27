import threading
from datetime import datetime, timezone
from typing import Literal

# Thread-safe sequence counter
_sequence_lock = threading.Lock()
_sequence = 0

OrderAction = Literal['BUY', 'SELL', 'HEDGE_OPEN', 'HEDGE_CLOSE']

def generate_order_id(action: OrderAction) -> str:
    """
    Generate a unique order ID composed of:
      - UTC timestamp in YYYYMMDDHHMMSSffffff format (timezone-aware)
      - action: one of 'buy', 'sell', 'hedge_open', 'hedge_close'
      - sequence number to avoid duplicates within the same microsecond

    Example:
        20250625123456789012_BUY_1
    """
    global _sequence
    # Validate action
    allowed = {'BUY', 'SELL', 'HEDGE_OPEN', 'HEDGE_CLOSE'}
    if action not in allowed:
        raise ValueError(f"Invalid action '{action}'. Must be one of {allowed}.")

    # Increment sequence in a thread-safe manner
    with _sequence_lock:
        _sequence += 1
        seq = _sequence

    # UTC timestamp with microsecond precision (timezone-aware)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")

    return f"{timestamp}_{action}_{seq}"
