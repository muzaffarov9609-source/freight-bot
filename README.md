# 🚛 Freight Broker Bot — O'rnatish Qo'llanmasi / Setup Guide

---

## 1-QADAM: Telegram Bot Yaratish

1. Telegramda **@BotFather** ni oching
2. `/newbot` yuboring
3. Bot nomini kiriting (masalan: `My Freight Bot`)
4. Username kiriting (masalan: `myfreight_bot`)
5. BotFather sizga **TOKEN** beradi — uni saqlang!
   ```
   1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ
   ```

---

## 2-QADAM: DAT API Kalitlarini Olish

1. https://dat.com ga kiring
2. Hisobingizga login qiling
3. **Developer Portal** → **API Access** ga boring
4. `Client ID` va `Client Secret` oling

> **Eslatma:** DAT API pulli. Agar siz demo rejimda sinab ko'rmoqchi bo'lsangiz, `YOUR_DAT_CLIENT_ID` va `YOUR_DAT_CLIENT_SECRET` ni bo'sh qoldiring — bot avtomatik DEMO data ishlatadi!

---

## 3-QADAM: Railway da Deploy Qilish (BEPUL)

### A) GitHub ga yuklash

1. https://github.com ga kiring (ro'yxatdan o'ting)
2. **New Repository** yarating → `freight-bot` deb nomlang
3. Ushbu fayllarni yuklang:
   - `bot.py`
   - `requirements.txt`
   - `railway.toml`

### B) Railway ga ulash

1. https://railway.app ga kiring
2. **GitHub** bilan login qiling
3. **New Project** → **Deploy from GitHub repo**
4. `freight-bot` reponi tanlang

### C) Environment Variables qo'shish

Railway dashboard da **Variables** bo'limiga boring va qo'shing:

```
TELEGRAM_TOKEN   = sizning_bot_tokeningiz
DAT_CLIENT_ID    = sizning_dat_client_id
DAT_CLIENT_SECRET = sizning_dat_client_secret
```

4. **Deploy** tugmasini bosing ✅

---

## 4-QADAM: Bot ni Ishlatish

Telegram da botingizni oching va:

| Buyruq | Nima qiladi |
|--------|-------------|
| `/start` | Botni ishga tushirish |
| `/states` | Shtat tanlash (10 tagacha) |
| `/loads` | Tanlangan shtatlardagi yuklarni ko'rish |
| `/monitor on` | Avtomatik monitoring yoqish (har 5 daqiqa) |
| `/monitor off` | Monitoringni o'chirish |
| `/ban [load_id]` | Yukni scam sifatida ban qilish |
| `/settings` | Til sozlamalari |
| `/help` | Yordam |

---

## Bot Xususiyatlari

### 🔥 HOT Yuk Aniqlash
- `$3.00/mil` dan yuqori narx
- 1000+ millik marshrut
- Yuqori talab ko'p bo'lgan shtatlar (CA, TX, FL, IL, OH...)

### 🚫 SCAM Aniqlash
- MC raqami yo'q brokerlar
- Oldindan to'lov talab qiluvchilar
- Shubhali yuqori narxlar ($10+/mil)
- Western Union / Zelle only

### 📊 Monitoring
- Har 5 daqiqada avtomatik yangi yuklar tekshiriladi
- Faqat HOT yuklar haqida bildirishnoma keladi
- Scam yuklar avtomatik filtrlanadi

---

## Muammolar / Troubleshooting

**Bot javob bermayapti?**
→ Railway dashboard da loglarni tekshiring

**DAT API ishlamayapti?**
→ Demo mode da ishlaydi, haqiqiy yuklar uchun DAT subscription kerak

**"No loads found" deyapti?**
→ Boshqa shtatlarni tanlang yoki biroz kutib qayta urinib ko'ring

---

## Texnologiyalar

- **Python 3.11** — asosiy til
- **python-telegram-bot 20.7** — Telegram API
- **aiohttp** — asinxron HTTP so'rovlar
- **APScheduler** — monitoring scheduler
- **Railway** — bepul cloud hosting

---

*Muammo bo'lsa, bot kodi `bot.py` faylida — o'zingiz xohlagan o'zgartirishlarni qilishingiz mumkin!*
