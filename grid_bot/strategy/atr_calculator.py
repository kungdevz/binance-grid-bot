from typing import Optional, List, Tuple, Dict
import numpy as np
import pandas as pd


class ATRCalculator:

    def __init__(self):
        pass

    def _calc_tr_single(high: float, low: float, prev_close: Optional[float]) -> float:
        """
        True Range (TR) ต่อ 1 แท่ง:
        TR = max(H-L, |H-Cp|, |L-Cp|)
        ถ้าไม่มี previous close (แท่งแรก) → ใช้แค่ H-L
        """
        if prev_close is None:
            return float(high - low)

        tr1 = high - low
        tr2 = abs(high - prev_close)
        tr3 = abs(low - prev_close)
        return float(max(tr1, tr2, tr3))

    def _calc_atr_from_history(tr_hist: List[float], tr_current: float, periods: Tuple[int, ...] = (14, 28)) -> Dict[int, float]:
        """
        คำนวณ ATR หลาย period จาก
        - tr_hist: list ของ TR ย้อนหลัง
        - tr_current: TR ของแท่งปัจจุบัน
        return: {period: atr_value}
        """
        all_tr = tr_hist + [tr_current]
        atr_values: Dict[int, float] = {}

        for p in periods:
            window = all_tr[-p:]
            atr_values[p] = float(np.mean(window)) if window else 0.0

        return atr_values

    def _calc_ema_from_history(hist: pd.DataFrame, close: float, periods: Tuple[int, ...] = (14, 28, 50, 100, 200)) -> Dict[str, float]:
        """
        คำนวณ EMA หลาย period จากข้อมูลแท่งล่าสุดใน hist + close ปัจจุบัน
        ถ้ายังไม่มีค่า EMA เดิม → ใช้ close ปัจจุบันเป็นค่าเริ่มต้น
        """
        if not hist.empty:
            prev = hist.iloc[-1]
        else:
            prev = None

        ema_values: Dict[str, float] = {}

        for period in periods:
            col_name = f"ema_{period}"
            alpha = 2 / (period + 1)

            if prev is None or col_name not in prev or pd.isna(prev[col_name]):
                # แท่งแรก → seed ด้วย close ปัจจุบัน
                ema_values[col_name] = float(close)
            else:
                prev_val = float(prev[col_name])
                ema_values[col_name] = float(alpha * close + (1 - alpha) * prev_val)

        return ema_values

    def _calc_tr_series(df: pd.DataFrame) -> pd.Series:
        """
        คืนค่า pandas Series ของ TR สำหรับทุกแท่งใน df
        df ต้องมีคอลัมน์: high, low, close
        """

        if df.empty:
            return pd.Series(dtype=float)

        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)

        # previous close
        prev_close = close.shift(1)

        # TR components
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()

        # True Range = max(tr1, tr2, tr3)
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # if the first candle have not prev_close, so we use TR = high - low
        tr.iloc[0] = tr1.iloc[0]

        return tr
