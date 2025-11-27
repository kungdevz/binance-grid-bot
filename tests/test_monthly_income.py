import pandas as pd
from pathlib import Path

from grid_bot.monthly_income import IncomeParams, calculate_monthly_income


def test_monthly_income_single_month(tmp_path: Path):
    # Build a minimal OHLCV dataset for one month
    data = {
        "Time": pd.date_range("2023-01-01", periods=120, freq="H"),
        "Open": [100.0] * 120,
        "High": [101.0] * 120,
        "Low": [99.0] * 120,
        "Close": [100.5] * 120,
        "Volume": [10.0] * 120,
    }
    df = pd.DataFrame(data)
    csv_path = tmp_path / "sample.csv"
    df.to_csv(csv_path, index=False)

    params = IncomeParams(
        symbol="TESTUSDT",
        symbol_future="TESTUSDT",
        initial_capital=1000.0,
        grid_levels=3,
        atr_multiplier=1.0,
        order_size_usdt=50.0,
        reserve_ratio=0.3,
        seed_history=10,
    )

    results = calculate_monthly_income(str(csv_path), params)
    # Should return exactly one month key
    assert list(results.keys()) == ["2023-01"]
    # PnL may be zero on flat data; ensure it returns a float
    assert isinstance(results["2023-01"], float)
