import ccxt
from typing import Dict, List, Any

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
    def __init__(self, spot: Any, symbol: str):
        self.spot = spot
        self.symbol = symbol

    def sync_grid_state(self, grid_prices: List[float]) -> Dict[float, bool]:
        state = {p: False for p in grid_prices}
        orders = self.spot.fetch_open_orders(self.symbol)
        for o in orders:
            if o.get('side') == 'buy' and o.get('status') in ['open', 'new']:
                price = round(float(o.get('price', 0)), 2)
                if price in state:
                    state[price] = True
        return state

    def place_limit_buy(self, symbol: str, price: float, qty: float) -> Any:
        return self.spot.create_order(symbol, 'limit', 'buy', qty, price)

    def place_market_order(self, symbol: str, side: str, qty: float) -> Any:
        return self.spot.create_order(symbol, 'market', side, qty)
