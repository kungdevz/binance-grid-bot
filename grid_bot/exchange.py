from decimal import Decimal
import ccxt, os
from typing import Dict, List, Any
from datetime import datetime, timezone
import grid_bot.utils.util as util

class ExchangeSync:
    """
    Sync grid state and orders with exchange.
    """
    def __init__(self, symbol_spot: str, symbol_future: str, mode: str = 'forward_test'):

        self.symbol_spot = symbol_spot
        self.symbol_futures = symbol_future
        if mode == 'live':
            self.spot = self.create_spot_exchanges(testnet=False)
            self.futures = self.create_future_exchanges(testnet=False)
            self.ensure_markets_loaded()
        elif mode == 'forward_test' or mode == 'back_test':
            self.spot = self.create_spot_exchanges(testnet=True)
            self.futures = self.create_future_exchanges(testnet=True)
            self.ensure_markets_loaded()
        else:
            self.spot = None
            self.futures = None
        
    def ensure_markets_loaded(self):
        if not self.spot.markets:
            self.spot.load_markets() 
        if not self.futures.market:
            self.futures.load_markets()

    def create_spot_exchanges(self, testnet: bool = False):

        api_spot_key = os.getenv("API_SPOT_KEY")    
        api_spot_secret = os.getenv("API_SPOT_SECRET")

        if testnet:
            api_spot_key = os.getenv("API_SPOT_KEY_TEST")
            api_spot_secret = os.getenv("API_SPOT_SECRET_TEST")

        spot = ccxt.binance({
            'apiKey': api_spot_key,
            'secret': api_spot_secret,
            'enableRateLimit': True,
            'options': {'defaultType': 'spot', 'adjustForTimeDifference': True}
        })

        if testnet:
            spot.set_sandbox_mode(True)
        
        return spot
    
    def create_future_exchanges(self, testnet: bool = False):

        api_future_key = os.getenv("API_FUTURE_KEY")
        api_future_secret = os.getenv("API_FUTURE_SECRET")

        if testnet:
            api_future_key = os.getenv("API_TEST_KEY_FUTURE")
            api_future_secret = os.getenv("API_TEST_SECRET_FUTURE")

        futures = ccxt.binance({
            'apiKey': api_future_key,
            'secret': api_future_secret,
            'enableRateLimit': True,
            'options': {'defaultType': 'future', 'adjustForTimeDifference': True}
        })

        if testnet:
            futures.set_sandbox_mode(True)
        
        return futures

    def sync_grid_state(self, grid_prices: List[float]) -> Dict[float, bool]:
        state = {p: False for p in grid_prices}
        orders = self.spot.fetch_open_orders(self.symbol_spot)
        for o in orders:
            if o.get('side') == 'buy' and o.get('status') in ['open', 'new']:
                price = round(float(o.get('price', 0)), 2)
                if price in state:
                    state[price] = True
        return state
    
    def query_sub_account(self) -> Dict[str, Any]:
        return self.spot.sapiGetSubAccountList()
    
    def fetch_open_orders(self) -> List[Dict[str, Any]]:
        return self.spot.fetch_open_orders(self.symbol_spot)

    def place_limit_buy(self, symbol: str, price: float, qty: float, exchange: bool) -> Any:
        if exchange:
            return self.spot.create_order(symbol, 'limit', 'buy', qty, price)
        else:
            return self._mock_order(symbol, "buy", price, qty)

    def place_limit_sell(self, symbol: str, price: float, qty: float, exchange: bool) -> Any:
        if exchange:
            return self.spot.create_order(symbol, 'limit', 'sell', qty, price)
        else:
            return self._mock_order(symbol, "sell", price, qty)
    
    def get_trade_spot_fee(self):
        return 1.0
    
    def get_market_info(self, symbol : str):
        market = self.spot.market(symbol)
        return market
    
    def get_market_precision(self,symbol : str, name : str):
        market = self.spot.market(symbol)
        precision = market["precision"][name]
        return precision

    def _build_spot_order_data(self, resp, grid_id):
        i = resp["info"]
        return {
            "grid_id": grid_id,
            "symbol": i["symbol"],
            "order_id": i["orderId"],
            "order_list_id": i.get("orderListId", "-1"),
            "client_order_id": i["clientOrderId"],
            "price": i["price"],
            "orig_qty": i["origQty"],
            "executed_qty": i["executedQty"],
            "cummulative_quote_qty": i["cummulativeQuoteQty"],
            "status": i["status"],
            "time_in_force": i["timeInForce"],
            "type": i["type"],
            "side": i["side"],
            "stop_price": i["stopPrice"],
            "iceberg_qty": i["icebergQty"],
            "binance_time": i["time"],
            "binance_update_time": i["updateTime"],
            "working_time": i.get("workingTime"),
            "is_working": int(i.get("isWorking", True)),
            "orig_quote_order_qty": i.get("origQuoteOrderQty", "0.00000000"),
            "self_trade_prevention_mode": i.get("selfTradePreventionMode"),
        }
    
    def _mock_order(self, symbol: str, side: str, price: float, qty: float):
        now_ms = int(datetime.now().timestamp() * 1000)
        order_id = now_ms
        client_order_id = f"mock-{order_id}"

        return {
            "info": {
                "symbol": symbol.replace("/", ""),     # BTCUSDT
                "orderId": order_id,
                "orderListId": "-1",
                "clientOrderId": client_order_id,
                "price": f"{price:.8f}",
                "origQty": f"{qty:.8f}",
                "executedQty": "0.00000000",
                "cummulativeQuoteQty": "0.00000000",
                "status": "NEW",
                "timeInForce": "GTC",
                "type": "LIMIT",
                "side": side.upper(),
                "stopPrice": "0.00000000",
                "icebergQty": "0.00000000",
                "time": now_ms,
                "updateTime": now_ms,
                "isWorking": True,
                "workingTime": now_ms,
                "origQuoteOrderQty": "0.00000000",
                "selfTradePreventionMode": "EXPIRE_MAKER"
            },

            # normalized fields (minimal subset)
            "id": str(order_id),
            "clientOrderId": client_order_id,
            "symbol": symbol,                     # BTC/USDT
            "type": "limit",
            "timeInForce": "GTC",
            "side": side.lower(),
            "price": float(price),
            "amount": float(qty),
            "cost": 0.0,
            "average": None,
            "filled": 0.0,
            "remaining": float(qty),
            "status": "open",
            "timestamp": now_ms,
            "datetime": datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
            "lastTradeTimestamp": None,
            "lastUpdateTimestamp": now_ms,
            "postOnly": False,
            "reduceOnly": None,
            "stopPrice": None,
            "takeProfitPrice": None,
            "stopLossPrice": None,
            "trades": [],
            "fees": [],
            "fee": None,
        }
