from typing import Dict
import pandas as pd


class SpacingCalculator:

    def __init__(self):
        pass

    def define_spacing_size(self, atr_period: int, history: pd.DataFrame) -> Dict["close":float, "spacing":float]:
        """
        Legacy helper for spacing sizing using TR/ATR on a High/Low/Close dataframe.
        """

        prev_close = 0.0

        if history is None or history.empty:
            return 0.0

        df = history.copy()
        # Normalize column names if capitalized
        high = df["High"] if "High" in df else df.get("high")
        low = df["Low"] if "Low" in df else df.get("low")
        close = df["Close"] if "Close" in df else df.get("close")
        tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)

        atr = tr.rolling(atr_period).mean()
        last_tr = float(tr.iloc[-1])
        last_atr = float(atr.iloc[-1]) if not pd.isna(atr.iloc[-1]) else float("nan")
        multiplier = 2.0 if last_tr > last_atr else 1.0

        try:
            prev_close = float(close.iloc[-1])
        except Exception:
            pass

        return {"spacing": float(last_tr * multiplier), "close": prev_close}
