import ccxt
from typing import Dict, List, Any
from datetime import datetime
from utils import utils

def create_exchanges(api_key: str, api_secret: str, testnet: bool = False):
    spot = ccxt.binance({
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True,
        'options': {'defaultType': 'spot', 'adjustForTimeDifference': True}
    })

    futures = ccxt.binance({
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True,
        'options': {'defaultType': 'future', 'adjustForTimeDifference': True}
    })

    if testnet:
        spot.set_sandbox_mode(True)
        futures.set_sandbox_mode(True)
    
    return spot, futures

class ExchangeSync:
    """
    Sync grid state and orders with exchange.
    """
    def __init__(self, spot: Any, symbol: str, mode: str = 'forward_test'):
        self.spot = spot
        self.symbol = symbol
        self.mode = mode

    def sync_grid_state(self, grid_prices: List[float]) -> Dict[float, bool]:
        state = {p: False for p in grid_prices}
        orders = self.spot.fetch_open_orders(self.symbol)
        for o in orders:
            if o.get('side') == 'buy' and o.get('status') in ['open', 'new']:
                price = round(float(o.get('price', 0)), 2)
                if price in state:
                    state[price] = True
        return state

    def place_limit_buy(self, symbol: str, price: float, qty: float, exchange: True) -> Any:
        if exchange:             
            return self.spot.create_order(symbol, 'limit', 'buy', qty, price)
        else:
            return {'symbol': symbol, 'side': 'buy', 'order_id': utils.generate_order_id("BUY"), 'type': 'limit', 'price': price, 'amount': qty, 'status': 'open', 'timestamp': datetime.now().timestamp()}
    
    def place_limit_sell(self, symbol: str, price: float, qty: float, exchange: True) -> Any:
        if exchange:             
            return self.spot.create_order(symbol, 'limit', 'sell', qty, price, )
        else:
            return {'symbol': symbol, 'side': 'sell', 'order_id': utils.generate_order_id("SELL"), 'type': 'limit', 'price': price, 'amount': qty, 'status': 'open', 'timestamp': datetime.now().timestamp()}

