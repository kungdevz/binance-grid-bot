import pandas as pd
from datetime import datetime
from typing import Any, Dict, List, Optional

from grid_bot.base_strategy import BaseGridStrategy
from grid_bot.dataclass.position import Position


class FakeLogger:
    def log(self, msg, level="INFO"):
        return


class FakeGridState:
    def __init__(self):
        self.rows: List[Dict[str, Any]] = []

    def save_state(self, entry: dict):
        self.rows.append(entry)
        return len(self.rows)

    def deactivate_group(self, symbol: str, group_id: str, reason: str = "RECENTER"):
        for r in self.rows:
            if r.get("group_id") == group_id:
                r["use_status"] = "N"
        return 1

    def close_open_orders_by_group(self, *args, **kwargs):
        return 0

    def load_state_with_use_flgs(self, symbol, use_flgs: str = "Y"):
        return [r for r in self.rows if r.get("use_status") == use_flgs]

    def delete_all_states(self):
        self.rows.clear()


class FakeSpotOrders:
    def __init__(self):
        self.rows: List[Dict[str, Any]] = []

    def close_open_orders_by_group(self, *args, **kwargs):
        return 0

    def create_order(self, data):
        self.rows.append(data)
        return len(self.rows)


class FakeFuturesOrders:
    def __init__(self):
        self.rows: List[Dict[str, Any]] = []

    def create_hedge_open(self, symbol: str, qty: float, price: float, leverage: int, side: str = "SELL"):
        row = {
            "id": len(self.rows) + 1,
            "order_id": len(self.rows) + 100,
            "symbol": symbol,
            "qty": qty,
            "price": price,
            "status": "OPEN",
            "side": side,
            "leverage": leverage,
        }
        self.rows.append(row)
        return row["order_id"]

    def close_hedge_order(self, order_id: int, close_price: float, realized_pnl: float):
        for r in self.rows:
            if r["order_id"] == order_id:
                r["status"] = "CLOSED"
                r["close_price"] = close_price
                r["realized_pnl"] = realized_pnl
                break

    def close_open_orders_by_group(self, symbol: str, reason: str = "RECENTER"):
        for r in self.rows:
            if r["symbol"] == symbol and r.get("status") in ("OPEN", "NEW"):
                r["status"] = "CANCELED"
        return 0


class FakeAccountBalance:
    def __init__(self):
        self.rows: List[Dict[str, Any]] = []

    def insert_balance_with_type(self, account_type: str, symbol: str = "", balance_usdt: float = 0.0, available_usdt: float = 0.0, notes: str = ""):
        row = {
            "account_type": account_type.upper(),
            "symbol": symbol,
            "record_date": datetime.now().strftime("%Y-%m-%d"),
            "record_time": datetime.now().strftime("%H:%M:%S"),
            "start_balance_usdt": balance_usdt,
            "end_balance_usdt": available_usdt,
            "notes": f"{account_type.upper()} {notes}".strip(),
        }
        self.rows.append(row)
        return len(self.rows)

    def get_latest_balance_by_type(self, account_type: str, symbol: str = ""):
        for r in reversed(self.rows):
            if r.get("account_type", "").startswith(account_type.upper()):
                return r
        return None

    def insert_balance(self, data):
        self.rows.append(data)
        return len(self.rows)

    def delete_all_balances(self):
        self.rows.clear()


class FakeOhlcvData:
    def __init__(self):
        self.rows: List[Dict[str, Any]] = []

    def get_recent_ohlcv(self, symbol: str, limit: int):
        df = pd.DataFrame(self.rows[-limit:])
        return df

    def insert_ohlcv_data(self, *args, **kwargs):
        from grid_bot.database.ohlcv_data import OhlcvData

        cols = ["symbol", "timestamp", "open", "high", "low", "close", "volume", "tr", "atr_14", "atr_28", "ema_14", "ema_28", "ema_50", "ema_100", "ema_200"]
        if args and isinstance(args[0], dict):
            data = {k: args[0].get(k) for k in cols}
        else:
            data = dict(zip(cols, args))
            data.update(kwargs)
        self.rows.append(data)
        return 1

    def delete_ohlcv_data(self, symbol: str, timestamp: int):
        before = len(self.rows)
        self.rows = [r for r in self.rows if not (r.get("symbol") == symbol and r.get("timestamp") == timestamp)]
        return before - len(self.rows)

    def get_recent_ohlcv_by_timestamp(self, symbol: str, timestamp: int, limit: int = 100):
        return [r for r in self.rows if r.get("symbol") == symbol and r.get("timestamp") <= timestamp][-limit:]


class FakeStrategy(BaseGridStrategy):
    """
    Strategy stub that bypasses DB connections and uses fakes.
    """

    def __init__(self, mode="backtest"):
        # do not call super().__init__ to avoid DB
        self.symbol = "BTCUSDT"
        self.symbol_future = "BTCUSDT"
        self.mode = mode
        self.initial_capital = 10000.0
        self.reserve_ratio = 0.0
        self.order_size_usdt = 100.0
        self.total_capital = self.initial_capital
        self.reserve_capital = 0.0
        self.available_capital = self.initial_capital
        self.grid_levels = 3
        self.atr_multiplier = 1.0
        self.grid_prices = []
        self.grid_filled = {}
        self.grid_group_id = "G1"
        self.grid_spacing = 5.0
        self.spot_fee_rate = 0.001
        self.positions: List[Position] = []
        self.realized_grid_profit = 0.0
        self.prev_close = None
        self.hedge_leverage = 2
        self.hedge_size_ratio = 0.5
        self.hedge_open_k_atr = 0.5
        self.hedge_tp_ratio = 0.5
        self.hedge_sl_ratio = 0.3
        self.min_hedge_notional = 1.0
        self.ema_fast_period = 14
        self.ema_mid_period = 50
        self.ema_slow_period = 200
        self.drift_k = 2.5
        self.vol_up_ratio = 1.5
        self.vol_down_ratio = 0.7
        # fakes
        self.grid_db = FakeGridState()
        self.spot_orders_db = FakeSpotOrders()
        self.futures_db = FakeFuturesOrders()
        self.acc_balance_db = FakeAccountBalance()
        self.ohlcv_db: Optional[FakeOhlcvData] = FakeOhlcvData()
        self.logger = FakeLogger()
        self.hedge_position = None
        self.futures_available_margin = 10000.0

    # implement abstract I/O
    def _io_place_spot_buy(self, *args, **kwargs):
        return {}

    def _io_place_spot_sell(self, *args, **kwargs):
        return {}

    def _io_open_hedge_short(self, timestamp_ms: int, qty: float, price: float, reason: str):
        return price

    def _io_close_hedge(self, timestamp_ms: int, qty: float, price: float, reason: str):
        return None

    def _run(self, timestamp_ms: int) -> None:
        # No-op for tests; required by abstract interface
        return

    # convenience wrapper for legacy tests
    def initialize_grid(self, symbol: str, base_price: float, spacing: float, levels: int):
        self.grid_levels = levels
        self.symbol = symbol
        self._init_lower_grid(timestamp_ms=0, base_price=base_price, atr=spacing, spacing_override=spacing)
        return self.grid_group_id
