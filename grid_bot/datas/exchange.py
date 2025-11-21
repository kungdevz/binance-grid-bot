from dataclasses import dataclass

@dataclass
class ExchangeConfig:
    spot_api_key: str
    spot_api_secret: str
    futures_api_key: str
    futures_api_secret: str
    use_spot_testnet: bool
    use_futures_testnet: bool
    enable_rate_limit: bool = True
    adjust_for_time_diff: bool = True
