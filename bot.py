"""
🚛 FREIGHT MONITOR BOT v3.0
Yangi funksiyalar:
- 📋 Book/Bid tugmasi
- ⭐ Broker review tizimi
- 📊 Haftalik hisobot
- 🔔 Narx ogohlantirish
- 🛡️ FMCSA/MC/email/phone tekshiruv
- 🚫 USPS yuklar filtri
- 🎨 Yangi dizayn
- 📡 Telegram kanallardan yuk olish
"""

import os
import json
import asyncio
import random
import re
import logging
from datetime import datetime, timedelta
from collections import defaultdict

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    BotCommand
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════
TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHANNEL_ID = os.getenv("CHANNEL_ID", "")
DAT_CLIENT_ID = os.getenv("DAT_CLIENT_ID", "demo")
DAT_CLIENT_SECRET = os.getenv("DAT_CLIENT_SECRET", "demo")

# Source Telegram channels to monitor for loads
SOURCE_CHANNELS = os.getenv("SOURCE_CHANNELS", "").split(",")  # e.g. "@channel1,@channel2"

ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "0").split(",") if x.strip().isdigit()]

US_STATES = [
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA",
    "HI","ID","IL","IN","IA","KS","KY","LA","ME","MD",
    "MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC",
    "SD","TN","TX","UT","VT","VA","WA","WV","WI","WY"
]

TRAILER_TYPES = {
    "VAN": "📦 Dry Van",
    "REEFER": "❄️ Reefer",
    "FLATBED": "🏗️ Flatbed",
    "STEPDECK": "📐 Step Deck",
    "LOWBOY": "⬇️ Lowboy",
    "POWER_ONLY": "🔌 Power Only",
    "BOX_TRUCK": "🚐 Box Truck",
    "HOTSHOT": "🔥 Hot Shot",
    "RGN": "🔩 RGN",
    "TANKER": "🛢️ Tanker"
}

# Known scam/suspicious email domains
SUSPICIOUS_DOMAINS = ["gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com"]
# Legitimate broker domains usually have company domain

# USPS / government keywords to filter
USPS_KEYWORDS = ["usps", "postal", "post office", "government load", "gov load",
                  "federal load", "irs", "dhs", "military load", "army load"]

# ═══════════════════════════════════════════
# IN-MEMORY DATABASE
# ═══════════════════════════════════════════
user_data = {}        # {user_id: {...}}
broker_reviews = {}   # {mc_number: [reviews]}
load_history = []     # seen loads
weekly_stats = defaultdict(lambda: {"seen": 0, "hot": 0, "scam": 0, "booked": 0})
price_alerts = {}     # {user_id: min_rate}
bid_history = {}      # {user_id: [bids]}
phone_registry = {}   # {phone: [mc_numbers]}  — detect MC mismatch


def get_user(user_id):
    if user_id not in user_data:
        user_data[user_id] = {
            "states": [],
            "trailer": "VAN",
            "monitoring": False,
            "language": "uz",
            "price_alert": 0,
            "bids": [],
            "seen_loads": set(),
        }
    return user_data[user_id]


# ═══════════════════════════════════════════
# BROKER VERIFICATION ENGINE 🛡️
# ═══════════════════════════════════════════
def verify_broker(mc_number: str, company_name: str, phone: str = "", email: str = "") -> dict:
    """
    Broker xavfsizligini tekshirish:
    - FMCSA authority age
    - MC mismatch
    - Email domain
    - Phone repeat
    - Carrier411 style signals
    """
    score = 100
    warnings = []
    signals = []

    # 1. MC raqami tekshirish
    if not mc_number or mc_number in ["N/A", "", "0"]:
        score -= 40
        warnings.append("🚨 MC raqami yo'q!")
    else:
        mc_clean = re.sub(r'\D', '', mc_number)
        if len(mc_clean) < 5:
            score -= 20
            warnings.append("⚠️ MC raqami qisqa/noto'g'ri")
        else:
            # Simulate FMCSA authority age check
            mc_num = int(mc_clean) if mc_clean.isdigit() else 0
            if mc_num > 3500000:  # Very new MC
                score -= 15
                warnings.append("⚠️ Yangi MC (< 1 yil) — ehtiyot bo'ling")
                signals.append("NEW_AUTHORITY")
            elif mc_num > 3000000:
                score -= 5
                signals.append("RELATIVELY_NEW")

    # 2. Phone repeat check (same phone, different MC)
    if phone:
        phone_clean = re.sub(r'\D', '', phone)
        if phone_clean in phone_registry:
            known_mcs = phone_registry[phone_clean]
            if mc_number and mc_number not in known_mcs:
                score -= 25
                warnings.append(f"🚨 Bu telefon boshqa MC bilan ham ro'yxatdan o'tgan!")
                signals.append("PHONE_MC_MISMATCH")
        else:
            phone_registry[phone_clean] = []
        if mc_number and mc_number not in phone_registry.get(phone_clean, []):
            phone_registry.setdefault(phone_clean, []).append(mc_number)

    # 3. Email domain check
    if email and "@" in email:
        domain = email.split("@")[1].lower()
        if domain in SUSPICIOUS_DOMAINS:
            score -= 20
            warnings.append(f"⚠️ Shaxsiy email domen ({domain}) — korporativ emas!")
            signals.append("PERSONAL_EMAIL")
    elif not email:
        score -= 10
        warnings.append("⚠️ Email ko'rsatilmagan")

    # 4. Company name checks
    if company_name:
        name_lower = company_name.lower()
        suspicious_words = ["transport llc", "trucking llc", "logistics llc"]
        generic_count = sum(1 for w in suspicious_words if w in name_lower)
        if generic_count >= 2:
            score -= 10
            signals.append("GENERIC_NAME")

    # 5. Broker reviews check
    if mc_number in broker_reviews:
        reviews = broker_reviews[mc_number]
        if reviews:
            avg = sum(r["rating"] for r in reviews) / len(reviews)
            if avg < 2.5:
                score -= 20
                warnings.append(f"⭐ Past reyting: {avg:.1f}/5 ({len(reviews)} sharh)")
                signals.append("LOW_RATING")
            elif avg >= 4.0:
                score += 5
                signals.append("HIGH_RATING")

    score = max(0, min(100, score))

    if score >= 75:
        status = "🟢 ISHONCHLI"
        emoji = "✅"
    elif score >= 50:
        status = "🟡 EHTIYOTKOR"
        emoji = "⚠️"
    else:
        status = "🔴 XAVFLI"
        emoji = "🚨"

    return {
        "score": score,
        "status": status,
        "emoji": emoji,
        "warnings": warnings,
        "signals": signals
    }


# ═══════════════════════════════════════════
# SCAM DETECTOR
# ═══════════════════════════════════════════
def is_scam_load(load: dict) -> tuple[bool, str]:
    reasons = []
    text = f"{load.get('broker','')} {load.get('notes','')}".lower()

    if load.get("mc_number") in ["N/A", "", None]:
        reasons.append("MC yo'q")
    if "advance" in text or "upfront" in text or "avans" in text:
        reasons.append("Avans to'lov")
    if "western union" in text or "zelle" in text or "venmo" in text:
        reasons.append("Shubhali to'lov usuli")
    if load.get("rate_per_mile", 0) > 8.0:
        reasons.append("Juda yuqori narx")
    if load.get("rate_per_mile", 0) < 0.5 and load.get("rate_per_mile", 0) > 0:
        reasons.append("Juda past narx")

    # USPS filter
    for kw in USPS_KEYWORDS:
        if kw in text or kw in load.get("origin", "").lower() or kw in load.get("dest", "").lower():
            reasons.append("USPS/Gov yuk — filter")
            break

    return bool(reasons), ", ".join(reasons)


def is_usps_load(load: dict) -> bool:
    text = f"{load.get('broker','')} {load.get('origin','')} {load.get('dest','')} {load.get('notes','')}".lower()
    return any(kw in text for kw in USPS_KEYWORDS)


# ═══════════════════════════════════════════
# LOAD FORMATTER 🎨
# ═══════════════════════════════════════════
def format_load(load: dict, index: int = 1) -> str:
    rate = load.get("rate_per_mile", 0)
    miles = load.get("miles", 0)
    total = rate * miles

    # HOT badge
    if rate >= 3.0 or miles >= 1000:
        hot_badge = "🔥 HOT LOAD"
    else:
        hot_badge = "📦 LOAD"

    broker_info = verify_broker(
        load.get("mc_number", ""),
        load.get("broker", ""),
        load.get("phone", ""),
        load.get("email", "")
    )

    stars = "⭐" * min(5, int(broker_info["score"] / 20))

    text = f"""
╔══════════════════════════════╗
║  {hot_badge} #{index}
╠══════════════════════════════╣
🗺️  {load.get('origin','?')}  ➜  {load.get('dest','?')}
📏  {miles:,} mil   💰 ${rate:.2f}/mil   💵 ~${total:,.0f}
🚛  {TRAILER_TYPES.get(load.get('trailer','VAN'), load.get('trailer','Van'))}
📅  Pickup: {load.get('pickup_date','?')}   ⚖️ {load.get('weight','?')} lbs
╠══════════════════════════════╣
🏢  {load.get('broker','?')}
🆔  MC: {load.get('mc_number','N/A')}
📞  {load.get('phone','N/A')}
📧  {load.get('email','N/A')}
╠══════════════════════════════╣
{broker_info['emoji']} Broker: {broker_info['status']} ({broker_info['score']}/100)
{stars}
"""
    if broker_info["warnings"]:
        text += "⚠️ " + " | ".join(broker_info["warnings"][:2]) + "\n"

    text += "╚══════════════════════════════╝"
    return text


# ═══════════════════════════════════════════
# DEMO DATA GENERATOR
# ═══════════════════════════════════════════
BROKERS = [
    {"name": "Coyote Logistics", "mc": "MC-366757", "phone": "888-225-3968", "email": "ops@coyotelogistics.com"},
    {"name": "Echo Global", "mc": "MC-466863", "phone": "800-354-7993", "email": "dispatch@echo.com"},
    {"name": "Transplace", "mc": "MC-479819", "phone": "866-787-2672", "email": "loads@transplace.com"},
    {"name": "TQL", "mc": "MC-488551", "phone": "800-580-3101", "email": "freight@tql.com"},
    {"name": "XPO Logistics", "mc": "MC-331455", "phone": "855-976-6747", "email": "ops@xpo.com"},
    {"name": "CH Robinson", "mc": "MC-152132", "phone": "800-323-7587", "email": "info@chrobinson.com"},
    {"name": "Landstar", "mc": "MC-299157", "phone": "888-438-2112", "email": "agent@landstar.com"},
    {"name": "Unknown LLC", "mc": "", "phone": "702-555-1234", "email": "broker99@gmail.com"},  # scam
    {"name": "Fast Transport LLC", "mc": "MC-3812345", "phone": "702-555-1234", "email": "fast@gmail.com"},  # suspicious
]

CITIES = {
    "CA": ["Los Angeles", "Fresno", "Sacramento", "San Diego", "Oakland"],
    "TX": ["Houston", "Dallas", "Austin", "San Antonio", "El Paso"],
    "FL": ["Miami", "Tampa", "Orlando", "Jacksonville", "Fort Lauderdale"],
    "NY": ["New York City", "Buffalo", "Albany", "Syracuse", "Rochester"],
    "IL": ["Chicago", "Rockford", "Peoria", "Springfield", "Aurora"],
    "GA": ["Atlanta", "Savannah", "Augusta", "Columbus", "Macon"],
    "OH": ["Columbus", "Cleveland", "Cincinnati", "Toledo", "Akron"],
    "PA": ["Philadelphia", "Pittsburgh", "Allentown", "Erie", "Reading"],
    "TN": ["Nashville", "Memphis", "Knoxville", "Chattanooga", "Clarksville"],
    "NC": ["Charlotte", "Raleigh", "Greensboro", "Durham", "Winston-Salem"],
}

def generate_demo_loads(states: list, trailer: str, count: int = 8) -> list:
    loads = []
    state_list = states if states else list(CITIES.keys())[:5]

    for i in range(count):
        orig_state = random.choice(state_list)
        dest_state = random.choice(US_STATES)
        orig_cities = CITIES.get(orig_state, [f"{orig_state} City"])
        dest_cities = CITIES.get(dest_state, [f"{dest_state} City"])

        broker = random.choice(BROKERS)
        miles = random.randint(150, 2500)
        rate = round(random.uniform(1.2, 5.5), 2)

        load = {
            "id": f"LOAD-{random.randint(10000,99999)}",
            "origin": f"{random.choice(orig_cities)}, {orig_state}",
            "dest": f"{random.choice(dest_cities)}, {dest_state}",
            "miles": miles,
            "rate_per_mile": rate,
            "trailer": trailer,
            "weight": random.choice([42000, 44000, 45000, 47000]),
            "pickup_date": (datetime.now() + timedelta(days=random.randint(0,3))).strftime("%m/%d/%Y"),
            "broker": broker["name"],
            "mc_number": broker["mc"],
            "phone": broker["phone"],
            "email": broker["email"],
            "notes": "",
        }
        loads.append(load)
    return loads


# ═══════════════════════════════════════════
# TELEGRAM CHANNEL SCRAPER SIMULATOR
# ═══════════════════════════════════════════
def parse_channel_message(text: str) -> dict | None:
    """
    Telegram broker kanallaridan kelgan xabarni parse qilish.
    Format: "Origin → Dest | Miles | Rate | Broker | MC | Phone"
    """
    if not text:
        return None

    # USPS filter
    text_lower = text.lower()
    for kw in USPS_KEYWORDS:
        if kw in text_lower:
            return None  # USPS yukni o'tkazib yuborish

    # Try to extract load info with regex
    load = {
        "id": f"TG-{random.randint(10000,99999)}",
        "origin": "Unknown",
        "dest": "Unknown",
        "miles": 0,
        "rate_per_mile": 0,
        "trailer": "VAN",
        "weight": 44000,
        "pickup_date": datetime.now().strftime("%m/%d/%Y"),
        "broker": "Unknown",
        "mc_number": "",
        "phone": "",
        "email": "",
        "notes": text[:100],
        "source": "telegram_channel"
    }

    # Extract MC number
    mc_match = re.search(r'MC[- #]?(\d{5,7})', text, re.IGNORECASE)
    if mc_match:
        load["mc_number"] = f"MC-{mc_match.group(1)}"

    # Extract phone
    phone_match = re.search(r'(\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})', text)
    if phone_match:
        load["phone"] = phone_match.group(1)

    # Extract email
    email_match = re.search(r'[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}', text)
    if email_match:
        load["email"] = email_match.group(0)

    # Extract rate
    rate_match = re.search(r'\$(\d+\.?\d*)\s*/?\s*mi(le)?', text, re.IGNORECASE)
    if rate_match:
        load["rate_per_mile"] = float(rate_match.group(1))

    # Extract miles
    miles_match = re.search(r'(\d{3,4})\s*(mi|mile|miles)', text, re.IGNORECASE)
    if miles_match:
        load["miles"] = int(miles_match.group(1))

    # Extract trailer type
    for t_key in TRAILER_TYPES:
        if t_key.lower() in text_lower or TRAILER_TYPES[t_key].lower() in text_lower:
            load["trailer"] = t_key
            break

    # Extract states
    state_pattern = r'\b(' + '|'.join(US_STATES) + r')\b'
    states_found = re.findall(state_pattern, text)
    if len(states_found) >= 2:
        load["origin"] = states_found[0]
        load["dest"] = states_found[1]

    return load


# ═══════════════════════════════════════════
# COMMANDS
# ═══════════════════════════════════════════

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    name = update.effective_user.first_name or "Driver"

    text = f"""
🚛 *Freight Monitor Bot v3.0* ga xush kelibsiz, {name}!

━━━━━━━━━━━━━━━━━━━━━
📋 *ASOSIY BUYRUQLAR*
━━━━━━━━━━━━━━━━━━━━━
/trailer — 🚛 Trailer type tanlash
/states — 🗺️ Shtatlar tanlash
/loads — 📦 Yuklarni ko'rish
/hot — 🔥 Faqat HOT yuklar
/monitor — 🔴 Auto monitoring
/alert — 🔔 Narx ogohlantirish

━━━━━━━━━━━━━━━━━━━━━
📊 *TAHLIL VA HISOBOT*
━━━━━━━━━━━━━━━━━━━━━
/rates — 📊 Narx tahlili
/stats — 💾 Statistika
/report — 📄 Haftalik hisobot
/broker — 🛡️ Broker tekshirish

━━━━━━━━━━━━━━━━━━━━━
⭐ *REVIEW VA BID*
━━━━━━━━━━━━━━━━━━━━━
/review — ⭐ Broker baholash
/mybids — 📋 Mening bidlarim

━━━━━━━━━━━━━━━━━━━━━
Hozirgi sozlamalar:
🚛 Trailer: {TRAILER_TYPES.get(user['trailer'], user['trailer'])}
🗺️ Shtatlar: {', '.join(user['states']) if user['states'] else 'Tanlanmagan'}
🔔 Alert: {'$' + str(user['price_alert']) + '/mil' if user['price_alert'] > 0 else 'O\'chirilgan'}
"""
    await update.message.reply_text(text, parse_mode="Markdown")


async def trailer_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    keyboard = []
    row = []
    for i, (key, label) in enumerate(TRAILER_TYPES.items()):
        row.append(InlineKeyboardButton(label, callback_data=f"trailer_{key}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    await update.message.reply_text(
        "🚛 *Trailer turini tanlang:*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def states_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    selected = user["states"]

    keyboard = []
    row = []
    for i, st in enumerate(US_STATES):
        mark = "✅" if st in selected else "⬜"
        row.append(InlineKeyboardButton(f"{mark}{st}", callback_data=f"state_{st}"))
        if len(row) == 5:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    keyboard.append([
        InlineKeyboardButton("🗑️ Hammasini tozalash", callback_data="states_clear"),
        InlineKeyboardButton("✅ Tayyor", callback_data="states_done")
    ])

    sel_text = f"Tanlangan: {', '.join(selected)}" if selected else "Hech narsa tanlanmagan"
    await update.message.reply_text(
        f"🗺️ *Shtatlarni tanlang* (bir nechta mumkin)\n_{sel_text}_",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def loads_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)

    if not user["states"]:
        await update.message.reply_text(
            "⚠️ Avval /states buyrug'i bilan shtatlarni tanlang!"
        )
        return

    msg = await update.message.reply_text("🔍 Yuklar qidirilmoqda...")

    loads = generate_demo_loads(user["states"], user["trailer"], count=6)

    shown = 0
    skipped_usps = 0
    skipped_scam = 0

    for i, load in enumerate(loads):
        # USPS filter
        if is_usps_load(load):
            skipped_usps += 1
            continue

        is_scam, reason = is_scam_load(load)
        if is_scam:
            skipped_scam += 1
            weekly_stats[datetime.now().strftime("%Y-W%W")]["scam"] += 1
            continue

        weekly_stats[datetime.now().strftime("%Y-W%W")]["seen"] += 1
        rate = load.get("rate_per_mile", 0)
        if rate >= 3.0 or load.get("miles", 0) >= 1000:
            weekly_stats[datetime.now().strftime("%Y-W%W")]["hot"] += 1

        text = format_load(load, shown + 1)

        # Check price alert
        alert_note = ""
        if user["price_alert"] > 0 and rate >= user["price_alert"]:
            alert_note = f"\n🔔 NARX OGOHLANTIRISH! ${rate:.2f}/mil ≥ ${user['price_alert']}/mil"

        keyboard = [
            [
                InlineKeyboardButton("📋 BID/BOOK", callback_data=f"bid_{load['id']}_{load['broker'][:15]}"),
                InlineKeyboardButton("⭐ Review", callback_data=f"rev_{load['mc_number']}_{load['broker'][:15]}"),
            ],
            [
                InlineKeyboardButton("🛡️ Broker tekshir", callback_data=f"check_{load['mc_number']}_{load['broker'][:15]}"),
                InlineKeyboardButton("🚫 Scam hisobot", callback_data=f"scam_{load['id']}"),
            ]
        ]

        await update.message.reply_text(
            text + alert_note,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None
        )
        shown += 1
        await asyncio.sleep(0.3)

    summary = f"""
━━━━━━━━━━━━━━━━━━━━━
📊 Natija: {shown} yuk ko'rsatildi
🚫 USPS/gov yuklar o'tkazib yuborildi: {skipped_usps}
🔴 Scam bloklandi: {skipped_scam}
━━━━━━━━━━━━━━━━━━━━━
"""
    await msg.edit_text(summary)


async def hot_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)

    loads = generate_demo_loads(user["states"] or list(CITIES.keys())[:5], user["trailer"], count=10)
    hot_loads = [l for l in loads if l["rate_per_mile"] >= 3.0 or l["miles"] >= 1000]
    hot_loads = [l for l in hot_loads if not is_usps_load(l)]
    hot_loads = [l for l in hot_loads if not is_scam_load(l)[0]]

    if not hot_loads:
        await update.message.reply_text("🔥 Hozircha HOT yuklar yo'q. Keyinroq qayta urinib ko'ring!")
        return

    await update.message.reply_text(f"🔥 *{len(hot_loads)} ta HOT yuk topildi!*", parse_mode="Markdown")

    for i, load in enumerate(hot_loads[:5]):
        text = format_load(load, i + 1)
        keyboard = [[
            InlineKeyboardButton("📋 BID/BOOK", callback_data=f"bid_{load['id']}_{load['broker'][:15]}"),
            InlineKeyboardButton("⭐ Review", callback_data=f"rev_{load['mc_number']}_{load['broker'][:15]}"),
        ]]
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        await asyncio.sleep(0.3)


async def monitor_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)
    args = ctx.args

    if args and args[0].lower() in ["on", "yoq", "start"]:
        user["monitoring"] = True
        if "monitor_job" not in ctx.chat_data:
            job = ctx.job_queue.run_repeating(
                monitor_task,
                interval=300,
                first=10,
                data={"user_id": uid, "chat_id": update.effective_chat.id}
            )
            ctx.chat_data["monitor_job"] = job
        await update.message.reply_text(
            "✅ Monitoring yoqildi!\nHar 5 daqiqada yangi HOT yuklar yuboriladi.\n/monitor off — o'chirish"
        )
    elif args and args[0].lower() in ["off", "o'chir", "stop"]:
        user["monitoring"] = False
        job = ctx.chat_data.pop("monitor_job", None)
        if job:
            job.schedule_removal()
        await update.message.reply_text("🔴 Monitoring o'chirildi.")
    else:
        status = "🟢 Yoqilgan" if user["monitoring"] else "🔴 O'chirilgan"
        await update.message.reply_text(
            f"📡 Monitoring holati: {status}\n\n"
            "/monitor on — yoqish\n"
            "/monitor off — o'chirish"
        )


async def monitor_task(ctx: ContextTypes.DEFAULT_TYPE):
    data = ctx.job.data
    uid = data["user_id"]
    chat_id = data["chat_id"]
    user = get_user(uid)

    if not user["monitoring"]:
        return

    loads = generate_demo_loads(user["states"] or list(CITIES.keys())[:3], user["trailer"], count=5)
    hot_new = []

    for load in loads:
        if load["id"] in user["seen_loads"]:
            continue
        if is_usps_load(load):
            continue
        if is_scam_load(load)[0]:
            continue
        rate = load.get("rate_per_mile", 0)
        miles = load.get("miles", 0)
        if rate >= 3.0 or miles >= 1000:
            # Price alert check
            if user["price_alert"] > 0 and rate >= user["price_alert"]:
                hot_new.append((load, True))  # True = alert triggered
            else:
                hot_new.append((load, False))
            user["seen_loads"].add(load["id"])

    if hot_new:
        await ctx.bot.send_message(chat_id, f"🔥 *{len(hot_new)} ta yangi HOT yuk!*", parse_mode="Markdown")
        for load, alert in hot_new[:3]:
            text = format_load(load)
            if alert:
                text = f"🔔 NARX OGOHLANTIRISH!\n" + text
            keyboard = [[
                InlineKeyboardButton("📋 BID/BOOK", callback_data=f"bid_{load['id']}_{load['broker'][:15]}"),
            ]]
            await ctx.bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(keyboard))
            await asyncio.sleep(0.3)


async def alert_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)
    args = ctx.args

    if args:
        try:
            rate = float(args[0])
            user["price_alert"] = rate
            await update.message.reply_text(
                f"🔔 Narx ogohlantirish o'rnatildi: *${rate:.2f}/mil dan yuqori*\n"
                "O'chirish uchun: /alert 0",
                parse_mode="Markdown"
            )
        except ValueError:
            await update.message.reply_text("❌ To'g'ri format: /alert 3.5")
    else:
        current = user["price_alert"]
        status = f"${current:.2f}/mil" if current > 0 else "O'chirilgan"
        await update.message.reply_text(
            f"🔔 Hozirgi ogohlantirish: *{status}*\n\n"
            "Yangi qiymat o'rnatish: /alert 3.5\n"
            "O'chirish: /alert 0",
            parse_mode="Markdown"
        )


async def rates_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)

    loads = generate_demo_loads(user["states"] or list(CITIES.keys()), user["trailer"], count=20)
    loads = [l for l in loads if not is_usps_load(l) and not is_scam_load(l)[0]]

    if not loads:
        await update.message.reply_text("📊 Tahlil qilish uchun yetarli ma'lumot yo'q.")
        return

    rates = [l["rate_per_mile"] for l in loads]
    avg = sum(rates) / len(rates)
    high = max(rates)
    low = min(rates)
    hot_count = sum(1 for r in rates if r >= 3.0)

    trend = "📈 O'sish" if avg > 2.5 else "📉 Tushish" if avg < 2.0 else "➡️ Barqaror"

    trailer = TRAILER_TYPES.get(user["trailer"], user["trailer"])
    states_str = ", ".join(user["states"]) if user["states"] else "Barcha shtatlar"

    text = f"""
📊 *NARX TAHLILI*
━━━━━━━━━━━━━━━━━━━━━
🚛 Trailer: {trailer}
🗺️ Shtatlar: {states_str}
📅 Sana: {datetime.now().strftime("%m/%d/%Y")}
━━━━━━━━━━━━━━━━━━━━━
📊 O'rtacha: *${avg:.2f}/mil*
📈 Eng yuqori: *${high:.2f}/mil*
📉 Eng past: *${low:.2f}/mil*
🔥 HOT yuklar: *{hot_count}/{len(loads)}*
{trend}
━━━━━━━━━━━━━━━━━━━━━
💡 Tavsiya: {"Yaxshi vaqt — ko'p yuk bor!" if avg >= 2.5 else "Kam yuk — shtatlarni kengaytiring"}
"""
    await update.message.reply_text(text, parse_mode="Markdown")


async def stats_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    week_key = datetime.now().strftime("%Y-W%W")
    ws = weekly_stats[week_key]

    text = f"""
💾 *STATISTIKA*
━━━━━━━━━━━━━━━━━━━━━
📅 Bu hafta ({week_key}):
📦 Ko'rilgan yuklar: *{ws['seen']}*
🔥 HOT yuklar: *{ws['hot']}*
🚫 Scam bloklandi: *{ws['scam']}*
📋 Bidlar: *{ws['booked']}*
━━━━━━━━━━━━━━━━━━━━━
Jami broker reytinglar: *{sum(len(v) for v in broker_reviews.values())}*
"""
    await update.message.reply_text(text, parse_mode="Markdown")


async def report_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    week_key = datetime.now().strftime("%Y-W%W")
    ws = weekly_stats[week_key]

    report_text = f"""
📄 HAFTALIK HISOBOT
Bot: Freight Monitor v3.0
Hafta: {week_key}
Sana: {datetime.now().strftime("%m/%d/%Y %H:%M")}

━━━ YUKLAR ━━━
Ko'rilgan: {ws['seen']}
HOT: {ws['hot']}
Scam bloklangan: {ws['scam']}
Bid/Book: {ws['booked']}

━━━ BROKER ━━━
Jami sharh: {sum(len(v) for v in broker_reviews.values())}
Faol brokerlar: {len(broker_reviews)}

━━━ SAMARADORLIK ━━━
Scam bloklash foizi: {(ws['scam'] / max(ws['seen'] + ws['scam'], 1) * 100):.1f}%
HOT foiz: {(ws['hot'] / max(ws['seen'], 1) * 100):.1f}%
"""

    # Send as text file
    import io
    file = io.BytesIO(report_text.encode("utf-8"))
    file.name = f"freight_report_{week_key}.txt"
    await update.message.reply_document(file, caption="📄 Haftalik hisobot")


async def broker_check_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if not args:
        await update.message.reply_text(
            "🛡️ Broker tekshirish:\n/broker MC-123456\n/broker MC-123456 company@email.com 555-1234"
        )
        return

    mc = args[0]
    email = args[1] if len(args) > 1 else ""
    phone = args[2] if len(args) > 2 else ""

    result = verify_broker(mc, "", phone, email)

    warn_text = "\n".join(f"• {w}" for w in result["warnings"]) if result["warnings"] else "✅ Ogohlantirish yo'q"
    sig_text = ", ".join(result["signals"]) if result["signals"] else "Yo'q"

    text = f"""
🛡️ *BROKER TEKSHIRUV*
━━━━━━━━━━━━━━━━━━━━━
🆔 MC: {mc}
━━━━━━━━━━━━━━━━━━━━━
{result['emoji']} Holat: *{result['status']}*
📊 Ball: *{result['score']}/100*
━━━━━━━━━━━━━━━━━━━━━
⚠️ Ogohlantirishlar:
{warn_text}
━━━━━━━━━━━━━━━━━━━━━
🔍 Signallar: {sig_text}
"""
    await update.message.reply_text(text, parse_mode="Markdown")


async def review_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if len(args) < 2:
        await update.message.reply_text(
            "⭐ Broker baholash:\n/review MC-123456 5\n"
            "(1=Yomon, 2=Past, 3=O'rtacha, 4=Yaxshi, 5=A'lo)"
        )
        return

    mc = args[0]
    try:
        rating = int(args[1])
        if rating < 1 or rating > 5:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Reyting 1 dan 5 gacha bo'lishi kerak!")
        return

    comment = " ".join(args[2:]) if len(args) > 2 else ""

    if mc not in broker_reviews:
        broker_reviews[mc] = []

    broker_reviews[mc].append({
        "rating": rating,
        "comment": comment,
        "user_id": update.effective_user.id,
        "date": datetime.now().isoformat()
    })

    reviews = broker_reviews[mc]
    avg = sum(r["rating"] for r in reviews) / len(reviews)
    stars = "⭐" * rating

    await update.message.reply_text(
        f"✅ Sharh qabul qilindi!\n\n"
        f"🆔 MC: {mc}\n"
        f"⭐ Sizning bahoyingiz: {stars} ({rating}/5)\n"
        f"📊 Umumiy o'rtacha: {avg:.1f}/5 ({len(reviews)} sharh)\n"
        f"💬 Izoh: {comment or 'Yo\'q'}"
    )


async def mybids_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)
    bids = user.get("bids", [])

    if not bids:
        await update.message.reply_text("📋 Hali bid qilmadingiz. Yuk ro'yxatida 'BID/BOOK' tugmasini bosing!")
        return

    text = "📋 *Mening bidlarim:*\n━━━━━━━━━━━━━━━\n"
    for i, bid in enumerate(bids[-10:], 1):
        text += f"{i}. {bid['load_id']} — {bid['broker']}\n   📅 {bid['date']}\n"

    await update.message.reply_text(text, parse_mode="Markdown")


# ═══════════════════════════════════════════
# CALLBACK HANDLERS
# ═══════════════════════════════════════════

async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    uid = query.from_user.id
    user = get_user(uid)

    # TRAILER SELECT
    if data.startswith("trailer_"):
        trailer = data.replace("trailer_", "")
        user["trailer"] = trailer
        label = TRAILER_TYPES.get(trailer, trailer)
        await query.edit_message_text(f"✅ Trailer tanlandi: *{label}*", parse_mode="Markdown")

    # STATE SELECT
    elif data.startswith("state_"):
        st = data.replace("state_", "")
        if st in user["states"]:
            user["states"].remove(st)
        else:
            if len(user["states"]) >= 15:
                await query.answer("⚠️ Maksimum 15 shtat!", show_alert=True)
                return
            user["states"].append(st)

        # Rebuild keyboard
        selected = user["states"]
        keyboard = []
        row = []
        for i, s in enumerate(US_STATES):
            mark = "✅" if s in selected else "⬜"
            row.append(InlineKeyboardButton(f"{mark}{s}", callback_data=f"state_{s}"))
            if len(row) == 5:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append([
            InlineKeyboardButton("🗑️ Hammasini tozalash", callback_data="states_clear"),
            InlineKeyboardButton("✅ Tayyor", callback_data="states_done")
        ])
        sel_text = f"Tanlangan ({len(selected)}): {', '.join(selected)}" if selected else "Hech narsa tanlanmagan"
        try:
            await query.edit_message_text(
                f"🗺️ *Shtatlarni tanlang*\n_{sel_text}_",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        except Exception:
            pass

    elif data == "states_clear":
        user["states"] = []
        await query.answer("🗑️ Tozalandi!")

    elif data == "states_done":
        sel = user["states"]
        if sel:
            await query.edit_message_text(
                f"✅ *{len(sel)} ta shtat tanlandi:* {', '.join(sel)}\n\n"
                "Yuklarni ko'rish uchun /loads",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text("⚠️ Hech narsa tanlanmadi. /states buyrug'i bilan qayta tanlang.")

    # BID / BOOK
    elif data.startswith("bid_"):
        parts = data.split("_", 2)
        load_id = parts[1] if len(parts) > 1 else "?"
        broker = parts[2] if len(parts) > 2 else "?"

        if "bids" not in user:
            user["bids"] = []

        user["bids"].append({
            "load_id": load_id,
            "broker": broker,
            "date": datetime.now().strftime("%m/%d/%Y %H:%M"),
            "status": "Pending"
        })
        weekly_stats[datetime.now().strftime("%Y-W%W")]["booked"] += 1

        await query.answer("📋 Bid qo'yildi!", show_alert=True)
        await query.message.reply_text(
            f"📋 *BID QO'YILDI!*\n\n"
            f"🆔 Yuk: {load_id}\n"
            f"🏢 Broker: {broker}\n"
            f"📅 Vaqt: {datetime.now().strftime('%m/%d/%Y %H:%M')}\n"
            f"📊 Holat: ⏳ Kutilmoqda\n\n"
            f"Bidlaringizni ko'rish: /mybids",
            parse_mode="Markdown"
        )

    # BROKER CHECK
    elif data.startswith("check_"):
        parts = data.split("_", 2)
        mc = parts[1] if len(parts) > 1 else ""
        company = parts[2] if len(parts) > 2 else ""

        result = verify_broker(mc, company)
        warn_text = "\n".join(f"• {w}" for w in result["warnings"]) if result["warnings"] else "✅ Ogohlantirish yo'q"

        await query.message.reply_text(
            f"🛡️ *BROKER TEKSHIRUV*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🏢 {company}\n"
            f"🆔 MC: {mc}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"{result['emoji']} {result['status']} ({result['score']}/100)\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"{warn_text}",
            parse_mode="Markdown"
        )

    # REVIEW
    elif data.startswith("rev_"):
        parts = data.split("_", 2)
        mc = parts[1] if len(parts) > 1 else ""
        company = parts[2] if len(parts) > 2 else ""

        keyboard = [
            [
                InlineKeyboardButton("⭐ 1", callback_data=f"rate_1_{mc}"),
                InlineKeyboardButton("⭐⭐ 2", callback_data=f"rate_2_{mc}"),
                InlineKeyboardButton("⭐⭐⭐ 3", callback_data=f"rate_3_{mc}"),
                InlineKeyboardButton("⭐⭐⭐⭐ 4", callback_data=f"rate_4_{mc}"),
                InlineKeyboardButton("⭐⭐⭐⭐⭐ 5", callback_data=f"rate_5_{mc}"),
            ]
        ]
        await query.message.reply_text(
            f"⭐ *{company}* brokerini baholang:\n_(1=Yomon, 5=Zo'r)_",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    # RATING GIVEN
    elif data.startswith("rate_"):
        parts = data.split("_", 2)
        rating = int(parts[1])
        mc = parts[2] if len(parts) > 2 else ""

        if mc not in broker_reviews:
            broker_reviews[mc] = []
        broker_reviews[mc].append({
            "rating": rating,
            "user_id": uid,
            "date": datetime.now().isoformat()
        })

        stars = "⭐" * rating
        await query.edit_message_text(
            f"✅ Rahmat! Bahoyingiz: {stars} ({rating}/5)\n"
            f"🆔 MC: {mc}"
        )

    # SCAM REPORT
    elif data.startswith("scam_"):
        load_id = data.replace("scam_", "")
        await query.answer("🚨 Scam xabari yuborildi! Rahmat.", show_alert=True)
        logger.warning(f"Scam reported: load_id={load_id} by user={uid}")


# ═══════════════════════════════════════════
# CHANNEL MESSAGE HANDLER
# ═══════════════════════════════════════════
async def channel_message_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Monitoring qilinayotgan kanallardan kelgan xabarlarni parse qilish"""
    msg = update.channel_post or update.message
    if not msg or not msg.text:
        return

    chat = msg.chat
    chat_username = f"@{chat.username}" if chat.username else str(chat.id)

    if SOURCE_CHANNELS and chat_username not in SOURCE_CHANNELS:
        return

    load = parse_channel_message(msg.text)
    if not load:
        return

    is_scam, reason = is_scam_load(load)
    if is_scam:
        logger.info(f"Scam load filtered from channel {chat_username}: {reason}")
        return

    # Forward to users who have monitoring on and matching states
    for user_id, udata in user_data.items():
        if not udata.get("monitoring"):
            continue
        if udata.get("states") and load.get("origin", "").split(", ")[-1] not in udata["states"]:
            continue
        if udata.get("trailer") and load.get("trailer") != udata.get("trailer"):
            continue

        text = format_load(load)
        text = f"📡 Kanal: {chat_username}\n" + text

        try:
            keyboard = [[
                InlineKeyboardButton("📋 BID/BOOK", callback_data=f"bid_{load['id']}_{load.get('broker','?')[:15]}"),
                InlineKeyboardButton("⭐ Review", callback_data=f"rev_{load.get('mc_number','')}_{load.get('broker','?')[:15]}"),
            ]]
            await ctx.bot.send_message(user_id, text, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            logger.error(f"Could not send to user {user_id}: {e}")


# ═══════════════════════════════════════════
# WEEKLY REPORT JOB
# ═══════════════════════════════════════════
async def weekly_report_job(ctx: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_IDS or ADMIN_IDS == [0]:
        return

    week_key = datetime.now().strftime("%Y-W%W")
    ws = weekly_stats[week_key]

    report_text = (
        f"📊 *Haftalik avtomatik hisobot*\n"
        f"Hafta: {week_key}\n\n"
        f"📦 Ko'rilgan: {ws['seen']}\n"
        f"🔥 HOT: {ws['hot']}\n"
        f"🚫 Scam: {ws['scam']}\n"
        f"📋 Bidlar: {ws['booked']}"
    )

    for admin_id in ADMIN_IDS:
        try:
            await ctx.bot.send_message(admin_id, report_text, parse_mode="Markdown")
        except Exception:
            pass


# ═══════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════
def main():
    if not TOKEN:
        logger.error("TELEGRAM_TOKEN topilmadi! Railway Variables da o'rnating.")
        return

    app = Application.builder().token(TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("trailer", trailer_cmd))
    app.add_handler(CommandHandler("states", states_cmd))
    app.add_handler(CommandHandler("loads", loads_cmd))
    app.add_handler(CommandHandler("hot", hot_cmd))
    app.add_handler(CommandHandler("monitor", monitor_cmd))
    app.add_handler(CommandHandler("alert", alert_cmd))
    app.add_handler(CommandHandler("rates", rates_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("report", report_cmd))
    app.add_handler(CommandHandler("broker", broker_check_cmd))
    app.add_handler(CommandHandler("review", review_cmd))
    app.add_handler(CommandHandler("mybids", mybids_cmd))

    # Callbacks
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Channel messages
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, channel_message_handler))

    # Weekly report job — every Monday 9am
    app.job_queue.run_daily(
        weekly_report_job,
        time=datetime.strptime("09:00", "%H:%M").time(),
        days=(0,),  # Monday
    )

    # Bot commands menu
    async def set_commands(app):
        await app.bot.set_my_commands([
            BotCommand("start", "🏠 Bosh sahifa"),
            BotCommand("trailer", "🚛 Trailer tanlash"),
            BotCommand("states", "🗺️ Shtatlar tanlash"),
            BotCommand("loads", "📦 Yuklarni ko'rish"),
            BotCommand("hot", "🔥 HOT yuklar"),
            BotCommand("monitor", "📡 Monitoring on/off"),
            BotCommand("alert", "🔔 Narx ogohlantirish"),
            BotCommand("rates", "📊 Narx tahlili"),
            BotCommand("stats", "💾 Statistika"),
            BotCommand("report", "📄 Haftalik hisobot"),
            BotCommand("broker", "🛡️ Broker tekshirish"),
            BotCommand("review", "⭐ Broker baholash"),
            BotCommand("mybids", "📋 Mening bidlarim"),
        ])

    app.post_init = set_commands

    logger.info("🚛 Freight Monitor Bot v3.0 ishga tushdi!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
