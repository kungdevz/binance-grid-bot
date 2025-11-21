from dataclasses import dataclass, field

@dataclass
class StrategyConfig:
    symbol_spot: str
    symbol_future: str
    initial_capital: float
    grid_levels: int
    atr_multiplier: float
    order_size_usdt: float
    reserve_ratio: float
    tp_pct: float = 0.02
    fallback_spacing_pct: float = 0.03
    spot_fee_rate: float = 0.001
    # hedge params
    hedge_trigger_atr_mult: float = 1.0
    hedge_size_ratio: float = 0.5
    hedge_leverage: int = 2