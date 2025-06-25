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

## 🧩 Parameters (ค่าเริ่มต้นที่แนะนำ)

| หมวดหมู่ | Parameter | ค่าตัวอย่าง / วิธีคำนวณ |
| --- | --- | --- |
| Grid | `grid_levels` | 5 ระดับ |
|  | `grid_spacing` | `ATR × multiplier` |
|  | `ATR_multiplier` | 2.0 (เมื่อ ATR > ค่าเฉลี่ย), 1.0 ปกติ |
|  | `order_size_usdt` | $500 ต่อไม้ |
| Hedge | `hedge_trigger` | ราคา < Lowest Grid − ATR |
|  | `hedge_size_ratio` | 50% ของ BNB ที่ถืออยู่ |
|  | `hedge_leverage` | 2x |
|  | `hedge_close_trigger` | ราคา > Hedge Entry + ATR |
| Capital | `initial_capital` | สำหรับ Backtest / Forword Test ทำเป็นตัวแปร <br> สำหรับ Live ดึงจาก API ของ CCTX Binance |
|  | `reserve_ratio` | 30% ของทุน ถือเป็นเงินสด |
| Fee | `spot_fee` | สำหรับ Backtest / Forword Test ทำเป็นตัวแปร <br> สำหรับ Live ดึงจาก API ของ CCTX Binance |
|  | `futures_fee` | สำหรับ Backtest / Forword Test ทำเป็นตัวแปร <br> สำหรับ Live ดึงจาก API ของ CCTX Binance |
|  | `funding_rate` | สำหรับ Backtest / Forword Test ทำเป็นตัวแปร 
สำหรับ Live ดึงจาก API ของ CCTX Binance |

---

## 🔄 เวิร์กโฟลว์โดยย่อ (แบบ Live)

1. ✅ **รับแท่งราคาจาก WebSocket (1h)**
2. ✅ คำนวณ ATR และ ATR Mean จากข้อมูลสะสม
3. ✅ ถ้ายังไม่เคยวาง Grid → Init Grid ตามราคาและ Spacing
4. 🟢 ถ้าราคาต่ำกว่า Grid → ซื้อ Spot ที่ราคานั้น
5. 🧯 ป้องกัน ราคาหลุด Lowest Grid → เปิด Short Hedge ( คำนวน TP/SL ) ทุกครั้ง
6. 💾 ทุกคำสั่งจะถูกบันทึกใน SQLite เพื่อ Track / Back test