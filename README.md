# Grid Bot – ATR-Based Lower-Only Grid + Futures Hedge (USDT-Only)

## 1. Overview

This bot is designed as a **USDT-only spot grid trading system** enhanced with a **short-futures hedge** and **ATR-based dynamic spacing**:

- Capital is **100% USDT** — no long-term coin holding; spot positions exist only when opened by grid orders.  
- Uses **lower-only grid**: places BUY orders as price declines through predefined levels.  
- Grid spacing adapts dynamically based on **ATR(14/28)** to match market volatility.  
- When price breaks below the lowest grid → automatically opens **futures short hedge** to offset spot drawdown.  
- Hedge profit is used to **rebalance and reduce spot losses**.  
- Supports **Backtest / Forward Test** using simulation, and **Live Trading** via Binance Spot/Futures (ccxt).

---

## 2. Architecture

### 2.1 Strategy Layer

#### `BaseGridStrategy`
Core engine containing:

- Indicator engine: TR, ATR14, ATR28, EMA14/28/50/100/200  
- Grid management: initialize, recalc spacing, recenter grid  
- Spot trading workflow: BUY/SELL with profit target = entry + spacing  
- Hedge system: open/scale/close short positions, rebalance spot holdings  
- Writes OHLCV data and snapshots to DB (backtest).

#### `BacktestGridStrategy`
- Simulates spot and futures trades.  
- Writes simulated orders to DB.  
- Reads a CSV file: `Time,Open,High,Low,Close,Volume`.

#### `LiveGridStrategy`
- Executes real trades via `ExchangeSync`.  
- Syncs spot/futures balances into DB.  
- Converts Binance response into internal DB schema.

---

### 2.2 I/O Layer — `IGridIO`

Defines abstract methods:

- `_io_place_spot_buy(...)`  
- `_io_place_spot_sell(...)`  
- `_io_open_hedge_short(...)`  
- `_io_close_hedge(...)`  
- `_run(...)`

Concrete classes implement them for backtest or live.

---

### 2.3 Exchange Layer — `ExchangeSync`

- Spot: limit buy/sell  
- Futures: open/close shorts  
- Fetch spot/futures balances  
- Sync open orders with DB  
- Supports Binance testnet and demo via environment variables

---

### 2.4 Database Layer (MySQL)

All repos inherit from `BaseMySQLRepo`:

| Repository | Table | Purpose |
|-----------|--------|---------|
| `GridState` | `grid_state` | Active grid levels and spacing |
| `OhlcvData` | `ohlcv_data` | OHLCV + indicator storage |
| `SpotOrders` | `spot_orders` | Spot trade history |
| `FuturesOrders` | `futures_orders` | Hedge orders & PnL |
| `AccountBalance` | `account_balance` | Equity snapshots |
| `Logger` | `logs` | Application logging |

Schema is created automatically.

---

## 3. Core Strategy Workflow

### Step 1 — Update Indicators  
- Compute ATR/EMA  
- Insert OHLCV row

### Step 2 — Load Grid  
- Load active grid from DB if not loaded

### Step 3 — Initialize / Adjust / Recenter  
- Initialize grid on first run  
- Adjust spacing dynamically  
- Recenter grid when price drifts or grid nearly consumed

### Step 4 — BUY Logic  
BUY spot when price hits lower grid:

- Record position  
- Set sell target = entry + spacing  
- Deduct capital  
- Snapshot balance (backtest)

### Step 5 — SELL Logic  
SELL spot when price ≥ target:

- Realize profit  
- Add capital  
- Persist order record

### Step 6 — Hedge Logic  
Triggered when price breaks lowest grid:

- Open/scale hedge short  
- Close hedge on PnL or EMA/ATR reversal  
- Use hedge profit to reduce spot bag

---

## 4. Modes & Runner

### `app_runner.py`
Selects mode via environment:

| MODE | Description |
|------|-------------|
| `backtest` | Run simulation with OHLCV CSV |
| other | Live trading mode |

Includes a Binance WebSocket example to feed closed candles to strategy.

---

## 5. Environment Variables

### DB
```
DB_HOST
DB_USER
DB_PASSWORD
DB_NAME
DB_PORT
DB_POOL_SIZE
```

### Binance Keys
Spot:
```
API_SPOT_KEY
API_SPOT_SECRET
API_SPOT_KEY_TEST
API_SPOT_SECRET_TEST
```

Futures:
```
API_FUTURE_KEY
API_FUTURE_SECRET
API_TEST_KEY_FUTURE
API_TEST_SECRET_FUTURE
```

### Strategy
```
INITIAL_CAPITAL
GRID_LEVELS
ATR_MULTIPLIER
ORDER_SIZE_USDT
RESERVE_RATIO
SYMBOL
FUTURES_SYMBOL
OHLCV_FILE
```

### Logging
```
ENVIRONMENT = development | production
```

---

## 6. How to Run

### Install
```bash
pip install ccxt mysql-connector-python pandas numpy websockets python-dotenv
```

### Backtest Example
```bash
export MODE=backtest
export SYMBOL="BNB/USDT"
export FUTURES_SYMBOL="BNB/USDT"
export OHLCV_FILE="/mnt/data/ohlcv.csv"
python app_runner.py
```

### Live Example
```bash
export MODE=live
export SYMBOL="BNB/USDT"
export FUTURES_SYMBOL="BNB/USDT"
export INITIAL_CAPITAL=1000
python app_runner.py
```

---

## 7. File Structure

| File | Purpose |
|------|---------|
| `base_strategy.py` | Core grid & hedge engine |
| `backtest_strategy.py` | Backtest runner |
| `live_strategy.py` | Live trading |
| `exchange.py` | ccxt wrapper |
| `io_interface.py` | Abstract I/O |
| `app_runner.py` | Entry point + WS example |
| `grid_states.py` | Grid DB repo |
| `ohlcv_data.py` | OHLCV DB repo |
| `spot_orders.py` | Spot DB repo |
| `future_orders.py` | Futures/hedge DB repo |
| `account_balance.py` | Balance snapshots |
| `logger.py` | Logging to DB |
| `base_database.py` | MySQL pool |
