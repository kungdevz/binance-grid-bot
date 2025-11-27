import threading
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone
from typing import Literal


class Util:

    def __init__(self):
        self.sequence = 0
        self.sequence_lock = threading.Lock()

    def to_exchange_amount(self, amount_dec: Decimal, precision: int) -> float:
        step = Decimal("1").scaleb(-precision)  # 10^-precision
        return float(amount_dec.quantize(step, rounding=ROUND_DOWN))

    def to_exchange_price(self, price_dec: Decimal, precision: int) -> float:
        step = Decimal("1").scaleb(-precision)
        return float(price_dec.quantize(step, rounding=ROUND_DOWN))

    def timemstamp_ms_to_date(self, timestamp_ms: int) -> str:
        return datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    def generate_order_id(self, action: str) -> str:
        """
        Generate a unique order ID composed of:
        - UTC timestamp in YYYYMMDDHHMMSSffffff format (timezone-aware)
        - action: one of 'BUY', 'SELL', 'HEDGE_OPEN', 'HEDGE_CLOSE', 'INIT'
        - sequence number to avoid duplicates within the same microsecond

        Example:
            20250625123456789012_BUY_1
        """
        # Validate action
        allowed = {"BUY", "SELL", "HEDGE_OPEN", "HEDGE_CLOSE", "INIT"}
        if action not in allowed:
            raise ValueError(f"Invalid action '{action}'. Must be one of {allowed}.")

        # Increment sequence in a thread-safe manner using the instance lock
        with self.sequence_lock:
            self.sequence += 1
            seq = self.sequence

        # UTC timestamp with microsecond precision (timezone-aware)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")

        return f"{timestamp}_{action}_{seq}"

    def _mock_spot_order(self, symbol: str, side: str, price: float, qty: float, timestamp_ms: int = None, grid_id: int = 0):

        now_ms = int(datetime.now().timestamp() * 1000)
        order_id = now_ms
        client_order_id = f"mock-spot-{order_id}"

        now_ms = int(timestamp_ms or int(datetime.now().timestamp() * 1000))
        order_id = self.generate_order_id(action=side.upper())
        client_order_id = f"bt-{order_id}"
        notional = price * qty

        return {
            "info": {
                "grid_id": grid_id,
                "symbol": symbol,
                "orderId": order_id,
                "orderListId": "-1",
                "clientOrderId": client_order_id,
                "price": f"{price:.8f}",
                "origQty": f"{qty:.8f}",
                "executedQty": f"{qty:.8f}",
                "cummulativeQuoteQty": f"{notional:.8f}",
                "status": "FILLED",
                "timeInForce": "GTC",
                "type": "LIMIT",
                "side": side.upper(),
                "stopPrice": "0.00000000",
                "icebergQty": "0.00000000",
                "time": now_ms,
                "updateTime": now_ms,
                "workingTime": now_ms,
                "isWorking": 1,
                "origQuoteOrderQty": f"{notional:.8f}",
                "selfTradePreventionMode": "EXPIRE_MAKER",
            }
        }

    def _mock_order(self, symbol: str, side: str, price: float, qty: float):
        now_ms = int(datetime.now().timestamp() * 1000)
        order_id = now_ms
        client_order_id = f"mock-{order_id}"

        return {
            "info": {
                "symbol": symbol.replace("/", ""),  # BTCUSDT
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
                "selfTradePreventionMode": "EXPIRE_MAKER",
            },
            # normalized fields (minimal subset)
            "id": str(order_id),
            "clientOrderId": client_order_id,
            "symbol": symbol,  # BTC/USDT
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

    def _mock_futures_order(self, symbol: str, side: str, price: float, qty: float, leverage: int):
        now_ms = int(datetime.now().timestamp() * 1000)
        order_id = now_ms
        client_order_id = f"mock-fut-{order_id}"
        return {
            "info": {
                "symbol": symbol.replace("/", ""),
                "orderId": order_id,
                "clientOrderId": client_order_id,
                "price": f"{price:.8f}",
                "origQty": f"{qty:.8f}",
                "executedQty": f"{qty:.8f}",
                "cumQuote": f"{qty * price:.8f}",
                "status": "FILLED",
                "type": "LIMIT",
                "side": side.upper(),
                "time": now_ms,
                "updateTime": now_ms,
                "reduceOnly": side.lower() == "buy",
                "positionSide": "BOTH",
                "leverage": leverage,
            }
        }

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

    def _build_futures_order_data(self, resp):
        i = resp.get("info", resp)
        return {
            "order_id": i.get("orderId"),
            "client_order_id": i.get("clientOrderId"),
            "symbol": i.get("symbol"),
            "status": i.get("status", "NEW"),
            "type": i.get("type", "LIMIT"),
            "side": i.get("side"),
            "price": i.get("price"),
            "avg_price": i.get("avgPrice", i.get("price")),
            "orig_qty": i.get("origQty", i.get("orig_qty", 0)),
            "executed_qty": i.get("executedQty", 0),
            "cum_quote": i.get("cumQuote", i.get("cummulativeQuoteQty", 0)),
            "time_in_force": i.get("timeInForce", "GTC"),
            "stop_price": i.get("stopPrice", 0),
            "iceberg_qty": i.get("icebergQty", 0),
            "time": i.get("time"),
            "update_time": i.get("updateTime"),
            "is_working": int(i.get("isWorking", True)) if i.get("isWorking") is not None else 1,
            "position_side": i.get("positionSide", "BOTH"),
            "reduce_only": int(i.get("reduceOnly", False)),
            "close_position": int(i.get("closePosition", False)),
            "working_type": i.get("workingType", "CONTRACT_PRICE"),
            "price_protect": int(i.get("priceProtect", False)),
            "orig_type": i.get("origType", i.get("type", "LIMIT")),
            "margin_asset": i.get("marginAsset", "USDT"),
            "leverage": i.get("leverage"),
        }
