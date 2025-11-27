from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd

from grid_bot.backtest_strategy import BacktestGridStrategy


@dataclass
class IncomeParams:
    symbol: str
    symbol_future: str
    initial_capital: float
    grid_levels: int
    atr_multiplier: float
    order_size_usdt: float
    reserve_ratio: float
    seed_history: int = 100  # number of seed candles before running grid logic


def _load_ohlcv(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, parse_dates=["Time"])
    df = df.rename(
        columns={
            "Time": "time",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    df = df[["time", "open", "high", "low", "close", "volume"]]
    df = df.sort_values("time")
    df = df.set_index("time")
    return df


def calculate_monthly_income(csv_path: str, params: IncomeParams) -> Dict[str, float]:
    """
    Run independent monthly backtests and return net realized PnL per YYYY-MM.

    Assumptions:
    - Uses historical OHLCV only; no slippage, funding, or fees beyond strategy config.
    - Each month is independent (state reset per month).
    """
    df = _load_ohlcv(Path(csv_path))
    if df.empty:
        return {}

    monthly_results: Dict[str, float] = {}

    grouped = df.groupby(pd.Grouper(freq="M"))
    for period_end, month_df in grouped:
        if month_df.empty:
            continue
        month_key = period_end.strftime("%Y-%m")

        # Seed history
        seed = month_df.iloc[: params.seed_history]
        run_df = month_df.iloc[params.seed_history :]
        if run_df.empty:
            continue

        strat = BacktestGridStrategy(
            symbol=params.symbol,
            symbol_future=params.symbol_future,
            initial_capital=params.initial_capital,
            grid_levels=params.grid_levels,
            atr_multiplier=params.atr_multiplier,
            order_size_usdt=params.order_size_usdt,
            reserve_ratio=params.reserve_ratio,
            logger=None,
        )

        # feed candles
        for ts, row in run_df.iterrows():
            ts_ms = int(ts.timestamp() * 1000)
            strat.on_bar(
                ts_ms,
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
                float(row["volume"]),
                seed,
            )

        # realized PnL from grid sells + hedge closes
        monthly_results[month_key] = float(strat.realized_grid_profit)

    return monthly_results


def print_monthly_income(monthly_results: Dict[str, float]) -> None:
    if not monthly_results:
        print("No monthly results.")
        return
    months = sorted(monthly_results.keys())
    total = 0.0
    print("Month\tIncome_USDT")
    for m in months:
        pnl = monthly_results[m]
        total += pnl
        print(f"{m}\t{pnl:.4f}")
    avg = total / len(months)
    print(f"Average\t{avg:.4f}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Estimate monthly income from grid backtests.")
    parser.add_argument("--csv", required=True, help="Path to OHLCV CSV (Time,Open,High,Low,Close,Volume)")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--symbol_future", required=True)
    parser.add_argument("--initial_capital", type=float, default=1000.0)
    parser.add_argument("--grid_levels", type=int, default=5)
    parser.add_argument("--atr_multiplier", type=float, default=1.0)
    parser.add_argument("--order_size_usdt", type=float, default=100.0)
    parser.add_argument("--reserve_ratio", type=float, default=0.3)
    parser.add_argument("--seed_history", type=int, default=100)
    args = parser.parse_args()

    monthly = calculate_monthly_income(
        csv_path=args.csv,
        params=IncomeParams(
            symbol=args.symbol,
            symbol_future=args.symbol_future,
            initial_capital=args.initial_capital,
            grid_levels=args.grid_levels,
            atr_multiplier=args.atr_multiplier,
            order_size_usdt=args.order_size_usdt,
            reserve_ratio=args.reserve_ratio,
            seed_history=args.seed_history,
        ),
    )
    print_monthly_income(monthly)
