import unittest
from datetime import datetime

from grid_bot.dataclass.position import Position
from tests.fakes import FakeAccountBalance, FakeLogger, FakeStrategy


class HedgeTests(unittest.TestCase):
    def test_hedge_tp_threshold_based_on_spot_loss(self):
        class SpyStrategy(FakeStrategy):
            def __init__(self):
                super().__init__(mode="backtest")
                self.closed_reason = None
                self.rebalanced = False

            def _close_hedge(self, timestamp_ms: int, price: float, reason: str) -> None:
                self.closed_reason = reason
                self.hedge_position = None

            def _rebalance_spot_after_hedge(self, timestamp_ms: int, hedge_pnl: float, price: float) -> None:
                self.rebalanced = True

        strat = SpyStrategy()
        strat.hedge_tp_ratio = 1.0
        strat.hedge_position = {"qty": 1.0, "entry": 100.0}
        # spot losing 10, hedge pnl 8 -> below threshold -> no close
        strat._manage_hedge_exit(timestamp_ms=0, price=92.0, spot_unrealized=-10.0, ema_fast=0, ema_mid=0)
        self.assertIsNone(strat.closed_reason)

        # hedge pnl 10 covers loss -> close with TP
        strat.hedge_position = {"qty": 1.0, "entry": 100.0}
        strat._manage_hedge_exit(timestamp_ms=0, price=90.0, spot_unrealized=-10.0, ema_fast=0, ema_mid=0)
        self.assertEqual(strat.closed_reason, "TP")
        self.assertTrue(strat.rebalanced)

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

    def test_buy_skips_when_insufficient_capital(self):
        strat = FakeStrategy()
        strat.available_capital = 10.0
        strat.grid_prices = [100.0]
        strat.grid_filled = {100.0: False}
        strat.order_size_usdt = 100.0
        strat._process_buy_grid(timestamp_ms=0, price=100.0)
        self.assertEqual(len(strat.spot_orders_db.rows), 0)
        self.assertEqual(strat.available_capital, 10.0)

    def test_hedge_not_opened_without_margin(self):
        strat = FakeStrategy()
        strat.futures_available_margin = 0.0
        strat.positions = [Position(symbol="BTCUSDT", side="LONG", entry_price=100.0, qty=1.0, grid_price=95.0, target_price=105.0, opened_at=0, group_id="G1")]
        strat._ensure_hedge_ratio(timestamp_ms=0, target_ratio=0.5, price=90.0, net_spot_qty=1.0, reason="NO_MARGIN")
        self.assertIsNone(strat.hedge_position)

    def test_hedge_closes_on_max_loss(self):
        strat = FakeStrategy()
        strat.positions = [Position(symbol="BTCUSDT", side="LONG", entry_price=100.0, qty=1.0, grid_price=95.0, target_price=105.0, opened_at=0, group_id="G1")]
        strat.hedge_position = {"qty": 1.0, "entry": 80.0, "timestamp": 0}
        strat._manage_hedge_exit(timestamp_ms=0, price=90.0, spot_unrealized=-10.0, ema_fast=0, ema_mid=0)
        self.assertIsNone(strat.hedge_position)

    def test_hedge_closes_on_reversal_after_hold(self):
        class RevSpy(FakeStrategy):
            def __init__(self):
                super().__init__()
                self.closed_reason = None

            def _close_hedge(self, timestamp_ms: int, price: float, reason: str) -> None:
                self.closed_reason = reason
                self.hedge_position = None

        strat = RevSpy()
        strat.hedge_min_hold_ms = 0
        strat.positions = [Position(symbol="BTCUSDT", side="LONG", entry_price=100.0, qty=1.0, grid_price=95.0, target_price=105.0, opened_at=0, group_id="G1")]
        strat.hedge_position = {"qty": 1.0, "entry": 100.0, "timestamp": 0}
        strat._manage_hedge_exit(timestamp_ms=1000, price=105.0, spot_unrealized=5.0, ema_fast=104.0, ema_mid=103.0)
        self.assertIsNone(strat.hedge_position)
        self.assertEqual(strat.closed_reason, "REVERSAL_CUT")

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

    def test_records_account_balance_on_hedge_open_close(self):
        strat = FakeStrategy()
        strat.positions = [Position(symbol="BTCUSDT", side="LONG", entry_price=100.0, qty=1.0, grid_price=95.0, target_price=105.0, opened_at=0, group_id="G1")]
        strat._ensure_hedge_ratio(target_ratio=0.5, price=90.0, net_spot_qty=1.0, reason="TEST_OPEN")
        self.assertTrue(any(r.get("notes") == "hedge_open" for r in strat.acc_balance_db.rows))
        # close hedge and ensure snapshot recorded
        strat.hedge_position = {"qty": 0.5, "entry": 90.0, "order_id": strat.futures_db.rows[0]["order_id"]}
        strat._close_hedge(timestamp_ms=2000, price=85.0, reason="TEST_CLOSE")
        self.assertTrue(any(r.get("notes") == "hedge_close" for r in strat.acc_balance_db.rows))


if __name__ == "__main__":
    unittest.main()
