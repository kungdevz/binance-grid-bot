import unittest
from datetime import datetime

from grid_bot.base_strategy import BaseGridStrategy
from grid_bot.datas.position import Position


class FakeLogger:
    def log(self, msg, level="INFO"):
        # Quiet logger for tests
        return


class FakeGridState:
    def __init__(self):
        self.rows = []

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


class FakeSpotOrders:
    def __init__(self):
        self.rows = []

    def close_open_orders_by_group(self, *args, **kwargs):
        return 0

    def create_order(self, data):
        self.rows.append(data)
        return len(self.rows)


class FakeFuturesOrders:
    def __init__(self):
        self.rows = []

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
        self.rows = []

    def insert_balance_with_type(self, account_type: str, balance_usdt: float, available_usdt: float, notes: str = ""):
        row = {
            "record_date": datetime.now().strftime("%Y-%m-%d"),
            "record_time": datetime.now().strftime("%H:%M:%S"),
            "start_balance_usdt": balance_usdt,
            "end_balance_usdt": available_usdt,
            "notes": f"{account_type.upper()} {notes}".strip(),
        }
        self.rows.append(row)
        return len(self.rows)

    def get_latest_balance_by_type(self, account_type: str):
        for r in reversed(self.rows):
            if r["notes"].startswith(account_type.upper()):
                return r
        return None

    def insert_balance(self, data):
        self.rows.append(data)
        return len(self.rows)


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
        self.positions = []
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
        self.ohlcv_db = None
        self.logger = FakeLogger()
        self.hedge_position = None
        self.futures_available_margin = 0.0

    def _io_place_spot_buy(self, *args, **kwargs):
        return {}

    def _io_place_spot_sell(self, *args, **kwargs):
        return {}

    def _io_open_hedge_short(self, qty: float, price: float, reason: str):
        return price

    def _io_close_hedge(self, qty: float, price: float, reason: str):
        return None


class HedgeTests(unittest.TestCase):
    def test_backtest_hedge_persists_open_close(self):
        strat = FakeStrategy(mode="backtest")
        # add one spot position to allow net_spot_qty
        strat.positions = [Position(symbol="BTCUSDT", side="LONG", entry_price=100.0, qty=1.0, grid_price=95.0, target_price=105.0, opened_at=0, group_id="G1")]
        strat._ensure_hedge_ratio(target_ratio=0.5, price=90.0, net_spot_qty=1.0, reason="TEST_OPEN")
        self.assertIsNotNone(strat.hedge_position)
        self.assertEqual(len(strat.futures_db.rows), 1)
        self.assertEqual(strat.futures_db.rows[0]["status"], "OPEN")

        # close hedge with profit
        strat._close_hedge(timestamp_ms=0, price=80.0, reason="TEST_CLOSE")
        self.assertIsNone(strat.hedge_position)
        self.assertEqual(strat.futures_db.rows[0]["status"], "CLOSED")
        self.assertIn("realized_pnl", strat.futures_db.rows[0])

    def test_recenter_skips_when_hedge_pnl_negative(self):
        strat = FakeStrategy()
        strat.grid_prices = [80.0, 85.0, 90.0]
        strat.grid_group_id = "GOLD"
        strat.grid_spacing = 5.0
        strat.hedge_position = {"qty": 1.0, "entry": 90.0}
        strat._maybe_recenter_grid(timestamp_ms=0, price=100.0, atr_14=1.0, atr_28=1.0)
        # grid should remain unchanged
        self.assertEqual(strat.grid_group_id, "GOLD")
        self.assertEqual(len(strat.grid_db.rows), 0)

    def test_recenter_closes_hedge_and_creates_new_grid_when_pnl_non_negative(self):
        strat = FakeStrategy()
        strat.grid_prices = [80.0, 85.0, 90.0]
        strat.grid_group_id = "GOLD"
        strat.grid_spacing = 5.0
        strat.hedge_position = {"qty": 1.0, "entry": 100.0, "order_id": 999}
        strat.positions = [Position(symbol="BTCUSDT", side="LONG", entry_price=85.0, qty=1.0, grid_price=85.0, target_price=90.0, opened_at=0, group_id="GOLD")]
        strat._maybe_recenter_grid(timestamp_ms=0, price=90.0, atr_14=1.0, atr_28=1.0)
        # hedge closed, new grid created
        self.assertIsNone(strat.hedge_position)
        self.assertNotEqual(strat.grid_group_id, "GOLD")
        active = [r for r in strat.grid_db.rows if r.get("use_status") == "Y"]
        inactive = [r for r in strat.grid_db.rows if r.get("use_status") == "N"]
        self.assertGreater(len(active), 0)
        self.assertGreaterEqual(len(inactive), 0)

    def test_strategy_reads_available_capital_from_db(self):
        strat = FakeStrategy()
        # seed balances
        strat.acc_balance_db.insert_balance_with_type("SPOT", balance_usdt=10000.0, available_usdt=8000.0)
        strat.acc_balance_db.insert_balance_with_type("FUTURES", balance_usdt=5000.0, available_usdt=3000.0)
        strat.available_capital = 0.0
        strat.futures_available_margin = 0.0
        strat._refresh_balances_from_db()
        self.assertEqual(strat.available_capital, 8000.0)
        self.assertEqual(strat.futures_available_margin, 3000.0)

    def test_live_hedge_persists_from_exchange_to_futures_orders(self):
        strat = FakeStrategy(mode="live")
        strat.positions = [Position(symbol="BTCUSDT", side="LONG", entry_price=100.0, qty=1.0, grid_price=95.0, target_price=105.0, opened_at=0, group_id="G1")]
        strat._ensure_hedge_ratio(target_ratio=0.3, price=90.0, net_spot_qty=1.0, reason="LIVE_OPEN")
        self.assertEqual(len(strat.futures_db.rows), 1)
        self.assertEqual(strat.futures_db.rows[0]["status"], "OPEN")
        self.assertIsNotNone(strat.hedge_position)

    def test_sync_balances_writes_spot_and_futures_to_db(self):
        # Build lightweight live strategy stub to reuse sync_balances_to_db
        from grid_bot.live_strategy import LiveGridStrategy
        live = object.__new__(LiveGridStrategy)
        live.acc_balance_db = FakeAccountBalance()
        live.logger = FakeLogger()
        class Ex:
            def fetch_spot_balance(self_inner):
                return {"USDT": {"total": 10000, "free": 8000}}
            def fetch_futures_balance(self_inner):
                return {"info": {"totalWalletBalance": 5000, "availableBalance": 4000}}
        live.exchange = Ex()
        live.sync_balances_to_db()
        # Verify two rows written
        notes = [r["notes"] for r in live.acc_balance_db.rows]
        self.assertTrue(any(n.startswith("SPOT") for n in notes))
        self.assertTrue(any(n.startswith("FUTURES") for n in notes))


if __name__ == "__main__":
    unittest.main()
