from decimal import Decimal
import os
from typing import Any, Dict, List
from datetime import datetime, timezone
import ccxt
import grid_bot.utils.util as util


class ExchangeSync:
    """
    Sync grid state and orders with exchange.
    """

    def __init__(
        self,
        symbol_spot: str,
        symbol_future: str,
        test_net: bool = False,
        load_markets: bool = True,
        spot_client: Any = None,
        futures_client: Any = None,
        **_: Any,
    ):
        self.symbol_spot = symbol_spot
        self.symbol_futures = symbol_future
        self.spot = spot_client or self.create_spot_exchanges(testnet=test_net)
        self.futures = futures_client or self.create_future_exchanges(testnet=test_net)
        if load_markets:
            self.ensure_markets_loaded()

    def ensure_markets_loaded(self):
        if not self.spot.markets:
            self.spot.load_markets()
        if not self.futures.markets:
            self.futures.load_markets()

    def create_spot_exchanges(self, testnet: bool = False):

        api_spot_key = os.getenv("API_SPOT_KEY")
        api_spot_secret = os.getenv("API_SPOT_SECRET")

        if testnet:
            api_spot_key = os.getenv("API_SPOT_KEY_TEST")
            api_spot_secret = os.getenv("API_SPOT_SECRET_TEST")

        spot = ccxt.binance({"apiKey": api_spot_key, "secret": api_spot_secret, "enableRateLimit": True, "options": {"defaultType": "spot", "adjustForTimeDifference": True}})

        if testnet:
            spot.set_sandbox_mode(True)

        return spot

    def create_future_exchanges(self, testnet: bool = False):

        api_future_key = os.getenv("API_FUTURE_KEY")
        api_future_secret = os.getenv("API_FUTURE_SECRET")

        if testnet:
            api_future_key = os.getenv("API_TEST_KEY_FUTURE")
            api_future_secret = os.getenv("API_TEST_SECRET_FUTURE")

        futures = ccxt.binance({"apiKey": api_future_key, "secret": api_future_secret, "enableRateLimit": True, "options": {"defaultType": "future", "adjustForTimeDifference": True}})

        if testnet:
            futures.set_sandbox_mode(True)

        return futures

    def sync_grid_state(self, grid_prices: List[float]) -> Dict[float, bool]:
        state = {p: False for p in grid_prices}
        orders = self.spot.fetch_open_orders(self.symbol_spot)
        for o in orders:
            if o.get("side") == "buy" and o.get("status") in ["open", "new"]:
                price = round(float(o.get("price", 0)), 2)
                if price in state:
                    state[price] = True
        return state

    def query_sub_account(self) -> Dict[str, Any]:
        return self.spot.sapiGetSubAccountList()

    def fetch_open_orders(self) -> List[Dict[str, Any]]:
        return self.spot.fetch_open_orders(self.symbol_spot)

    def place_limit_buy(self, symbol: str, price: float, qty: float, exchange: bool) -> Any:
        return self.spot.create_order(symbol, "limit", "buy", qty, price)

    def place_limit_sell(self, symbol: str, price: float, qty: float, exchange: bool) -> Any:
        return self.spot.create_order(symbol, "limit", "sell", qty, price)

    # ---------------- Futures helpers ----------------
    def place_futures_short(self, symbol: str, price: float, qty: float, leverage: int = 2, exchange: bool = True) -> Any:
        try:
            self.futures.set_leverage(leverage, symbol)
        except Exception:
            pass
        return self.futures.create_order(symbol, "limit", "sell", qty, price, params={"reduceOnly": False})

    def close_futures_position(self, symbol: str, qty: float, price: float, exchange: bool = True) -> Any:
        return self.futures.create_order(symbol, "limit", "buy", qty, price, params={"reduceOnly": True})

    def fetch_spot_balance(self) -> Dict[str, Any]:
        return self.spot.fetch_balance()

    def fetch_futures_balance(self) -> Dict[str, Any]:
        return self.futures.fetch_balance()

    def get_trade_spot_fee(self):
        return 1.0

    def get_market_info(self, symbol: str):
        market = self.spot.market(symbol)
        return market

    def get_market_precision(self, symbol: str, name: str):
        market = self.spot.market(symbol)
        precision = market["precision"][name]
        return precision
