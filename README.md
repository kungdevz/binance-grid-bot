# Grid Bot : ATR + Hedge Short

## สรุปหลัก: **USDT-Only Grid Bot + ATR + Hedge ( Neutral Short )**

### 🎯 เป้าหมาย

- ใช้ USDT เป็นทุนหลัก สร้างรายได้แบบ Passive ( Cash Flow )
- ซื้อสินทรัพย์ ที่ราคาลดลงตามกรอบ Grid แบบ Dynamic
- ป้องกันการ Drawdown รุนแรงด้วยการ Hedge (Short Futures)
- ปรับ Grid ตามความผันผวนของตลาด (ATR)
- ไม่มีการถือสินทรัพย์ระยะยาว (ถือเมื่อมี order เท่านั้น)

---

## 🧠 หลักการทำงาน

| ส่วน | รายละเอียด |
| --- | --- |
| 🔁 **Grid Strategy** | วางกรอบซื้อ (Buy only) ตามราคา ลดระดับลงเรื่อย ๆ |
| 📊 **ATR-Based Spacing** | ระยะห่างของ Grid (`spacing`) คำนวณจาก `ATR × multiplier` |
| 🔐 **Hedge Strategy** | เปิด Short Futures เมื่อราคามีแนวโน้มจะหลุด Lowest Grid. |
| 💡 **Close Hedge** | ปิด Hedge  ( PNL ต้องไม่ติดลบ ปิด Grid Order ขาย SPOT ที่มีทั้งหมด โดยเน้นรักษาต้นทุน นำกำไรจาก Short มาเฉลี่ย |
| 💾 **State** | เก็บคำสั่ง Buy ใน SQLite (หรือ sync จาก Binance หาก live) |

---

## 🔄 Work Flow

```
START (check configuration in .env (forward test or live)
│
├─> Initialize parameters, reserve ratio and grid levels is from .env then get captical
|   ├─> forward test mode, Get a capital it from .env file
|   ├─> Live mode, Get a capital (Account balance) from exchange
│
├─> Run in live mode, Connect exchanges (spot, futures) using API keys
|   ├─> Get Spot fee
|   ├─> Get Future fee
|   |─> Check Balance in account then update to 
|   |─> Check current spot postion (open and fill) then update status to spot_orders table (spot_orders.py)
|   └─> Check current future postion at Exchange then update status (Open and filled) to futures_orders table (futures_orders.py)
├─> Run in forward test mode all value in .env file.
|   ├─> Get Spot fee (.env file)
|   ├─> Get Future fee (.env file)
|   ├─> Check Balance in account (account_balance.py)
|   └─> Check current future postion (open and fill) then update status to futures_orders table (futures_orders.py)
│
├─> Fetch historical candles, forward test read from OHCLV file, live connect to exchange (last 30 Days).
│     ├─> Calculate TR and ATR(14)
│     ├─> Calculate multiplier from TR and ATR
│     ├─> Calculate initial grid spacing: ATR * multiplier
│     └─> Create initial grid prices (above & below base price)
│
├─> Place initial limit orders (simulate if forward test, real if live) 
│
├─> Start real-time price stream (websocket)
│
├─> LOOP: On new candle
│     ├─> Update ATR, ATR
│     ├─> Check if grid needs to adjust spacing (optional dynamic adjust)
│     ├─> Process buys:
│     │     ├─> If price <= grid level and not yet filled
│     │     │     ├─> Execute buy
│     │     │     ├─> Allocate USDT
│     │     │     └─> Update grid state, mark as filled
│     │     └─> Update positions
│     │
│     ├─> Process sells:
│     │     ├─> If price >= target price
│     │     │     ├─> Execute sell
│     │     │     ├─> Return USDT
│     │     │     ├─> Add realized profit
│     │     │     └─> Update grid state, mark as unfilled
│     │
│     ├─> Hedge logic:
│     │     ├─> If price < lowest grid - ATR and not hedged
│     │     │     ├─> Open short (hedge), size = % of spot position
│     │     │     └─> Mark hedge active
│     │     ├─> If price > hedge entry + ATR and hedge active
│     │     │     ├─> Close short (hedge)
│     │     │     └─> Add realized hedge profit
│     │
│     └─> Save updated state to DB (SQLite)
│
└─> END LOOP (runs until stopped)
```