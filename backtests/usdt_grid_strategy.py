
import pandas as pd
import numpy as np

class USDTGridStrategy:
    def __init__(self, initial_capital=10000, reserve_ratio=0.3, order_size_usdt=500,
                 spot_fee=0.001, futures_fee=0.0004, hedge_size_ratio=0.5, hedge_leverage=2):
        self.initial_capital = initial_capital
        self.reserve_ratio = reserve_ratio
        self.order_size_usdt = order_size_usdt
        self.spot_fee = spot_fee
        self.futures_fee = futures_fee
        self.hedge_size_ratio = hedge_size_ratio
        self.hedge_leverage = hedge_leverage
        self.reset()

    def reset(self):
        self.available_capital = self.initial_capital * (1 - self.reserve_ratio)
        self.reserve_capital = self.initial_capital * self.reserve_ratio
        self.realized_grid_profit = 0.0
        self.realized_hedge_profit = 0.0
        self.positions = []
        self.hedge_active = False
        self.hedge_entry_price = 0
        self.hedge_qty = 0
        self.spot_log = []
        self.futures_log = []

    def run(self, df):
        
        df['ATR'] = self.calculate_atr(df, period=14)
        df['ATR_mean'] = df['ATR'].rolling(window=100).mean()
        df = df.dropna()

        grid_initialized = False
        grid_prices = []

        for i, row in df.iterrows():
            price = row['Close']
            atr = row['ATR']
            atr_avg = row['ATR_mean']
            timestamp = row.name
            multiplier = 2.0 if atr > atr_avg else 1.0
            spacing = atr * multiplier

            if not grid_initialized:
                base_price = price
                grid_prices = [base_price - spacing * j for j in range(1, 4)]
                grid_initialized = True

            # Execute buy grid
            for grid_price in grid_prices:
                if price <= grid_price and self.available_capital >= self.order_size_usdt:
                    qty = self.order_size_usdt / grid_price
                    fee = self.order_size_usdt * self.spot_fee
                    self.available_capital -= (self.order_size_usdt + fee)
                    sell_price = grid_price + spacing
                    self.positions.append((qty, grid_price, sell_price, atr))
                    self.spot_log.append([timestamp, 'SPOT', 'Buy', grid_price, qty, self.order_size_usdt, atr, fee, None, 'Buy Grid'])

            # Sell when price hits sell level
            new_positions = []
            for qty, entry_price, sell_target, entry_atr in self.positions:
                if price >= sell_target:
                    notional = qty * price
                    fee = notional * self.spot_fee
                    pnl = notional - (qty * entry_price) - fee
                    self.available_capital += notional - fee
                    self.realized_grid_profit += pnl
                    self.spot_log.append([timestamp, 'SPOT', 'Sell', price, qty, notional, entry_atr, fee, pnl, 'Sell Grid'])
                else:
                    new_positions.append((qty, entry_price, sell_target, entry_atr))
            self.positions = new_positions

            # Hedge open
            if not self.hedge_active and price < min(grid_prices) - atr and len(self.positions) > 0:
                self.hedge_qty = sum(p[0] for p in self.positions) * self.hedge_size_ratio
                self.hedge_entry_price = price
                notional = self.hedge_qty * price
                fee = notional * self.futures_fee
                self.hedge_active = True
                self.futures_log.append([timestamp, 'FUTURES', 'Short', price, self.hedge_qty, notional, atr, fee, None, 'Hedge Open'])

            # Hedge close
            elif self.hedge_active and price > self.hedge_entry_price + atr:
                exit_notional = self.hedge_qty * price
                entry_notional = self.hedge_qty * self.hedge_entry_price
                pnl = entry_notional - exit_notional
                fee = exit_notional * self.futures_fee
                self.realized_hedge_profit += pnl - fee
                self.hedge_active = False
                self.hedge_qty = 0
                self.futures_log.append([timestamp, 'FUTURES', 'Close', price, self.hedge_qty, exit_notional, atr, fee, pnl, 'Hedge Close'])

        return self.get_summary()

    def calculate_atr(self, df, period=14):
        high_low = df['High'] - df['Low']
        high_close = np.abs(df['High'] - df['Close'].shift())
        low_close = np.abs(df['Low'] - df['Close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(period).mean()
        return atr

    def get_summary(self):
        return {
            "Final USDT Balance": round(self.available_capital + self.reserve_capital, 2),
            "Realized Grid Profit (USDT)": round(self.realized_grid_profit, 2),
            "Realized Hedge Profit (USDT)": round(self.realized_hedge_profit, 2),
            "Total Realized Profit (USDT)": round(self.realized_grid_profit + self.realized_hedge_profit, 2),
            "BNB Holdings (should be 0)": round(sum(p[0] for p in self.positions), 4),
            "Spot Trades": len(self.spot_log),
            "Hedge Trades": len(self.futures_log)
        }
