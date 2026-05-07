import os
import asyncio
import aiohttp
import json
import re
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import logging

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── CONFIG ───────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
DAT_CLIENT_ID  = os.getenv("DAT_CLIENT_ID", "demo")
DAT_CLIENT_SECRET = os.getenv("DAT_CLIENT_SECRET", "demo")
DAT_BASE_URL   = "https://freight.dat.com/v2"

# ─── US STATES ────────────────────────────────────────────────────────────────
US_STATES = {
    "AL": "Alabama",    "AK": "Alaska",     "AZ": "Arizona",    "AR": "Arkansas",
    "CA": "California", "CO": "Colorado",   "CT": "Connecticut","DE": "Delaware",
    "FL": "Florida",    "GA": "Georgia",    "HI": "Hawaii",     "ID": "Idaho",
    "IL": "Illinois",   "IN": "Indiana",    "IA": "Iowa",       "KS": "Kansas",
    "KY": "Kentucky",   "LA": "Louisiana",  "ME": "Maine",      "MD": "Maryland",
    "MA": "Massachusetts","MI": "Michigan", "MN": "Minnesota",  "MS": "Mississippi",
    "MO": "Missouri",   "MT": "Montana",    "NE": "Nebraska",   "NV": "Nevada",
    "NH": "New Hampshire","NJ": "New Jersey","NM": "New Mexico","NY": "New York",
    "NC": "North Carolina","ND": "North Dakota","OH": "Ohio",   "OK": "Oklahoma",
    "OR": "Oregon",     "PA": "Pennsylvania","RI": "Rhode Island","SC": "South Carolina",
    "SD": "South Dakota","TN": "Tennessee", "TX": "Texas",      "UT": "Utah",
    "VT": "Vermont",    "VA": "Virginia",   "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin",  "WY": "Wyoming"
}

HOT_STATES = {"CA", "TX", "FL", "IL", "OH", "GA", "NC", "PA", "TN", "AZ"}

SCAM_PATTERNS = [
    r'\b(advance|upfront)\s+fee\b',
    r'\bpay\s+first\b',
    r'\bwestern\s+union\b',
    r'\bzelle\s+only\b',
    r'\bcash\s+app\s+only\b',
]

# ─── IN-MEMORY STORAGE ────────────────────────────────────────────────────────
user_states = {}
banned_loads = set()
monitoring_users = {}
dat_token_cache = {"token": None, "expires": None}
sent_load_ids = set()

# ─── TRANSLATIONS ─────────────────────────────────────────────────────────────
TEXTS = {
    "uz": {
        "welcome": "🚛 *Freight Broker Bot ga xush kelibsiz!*\n\nAmerika bo'ylab yuklarni kuzating!\n\n📍 /states - Shtat tanlash\n📊 /loads - Yuklarni ko'rish\n🔴 /monitor - Monitoring\n⚙️ /settings - Sozlamalar\n❓ /help - Yordam",
        "choose_state": "📍 *Shtat tanlang:*",
        "no_states": "⚠️ Shtat tanlanmagan. /states buyrug'i bilan tanlang.",
        "monitoring_on": "✅ Monitoring yoqildi! HOT yuklar kelganda xabar olasiz.",
        "monitoring_off": "⛔ Monitoring o'chirildi.",
        "no_loads": "📭 Hozir bu shtatda yuk topilmadi.",
        "loading": "⏳ Yuklar qidirilmoqda...",
    },
    "en": {
        "welcome": "🚛 *Welcome to Freight Broker Bot!*\n\nMonitor loads across the US!\n\n📍 /states - Select states\n📊 /loads - View loads\n🔴 /monitor - Monitoring\n⚙️ /settings - Settings\n❓ /help - Help",
        "choose_state": "📍 *Select State:*",
        "no_states": "⚠️ No states selected. Use /states to select.",
        "monitoring_on": "✅ Monitoring enabled! You'll get alerts for HOT loads.",
        "monitoring_off": "⛔ Monitoring disabled.",
        "no_loads": "📭 No loads found right now.",
        "loading": "⏳ Searching for loads...",
    }
}

def t(user_id, key):
    lang = user_states.get(user_id, {}).get("language", "uz")
    return TEXTS[lang].get(key, TEXTS["en"].get(key, key))

# ─── DAT API / DEMO DATA ──────────────────────────────────────────────────────
async def get_dat_token():
    now = datetime.utcnow()
    if dat_token_cache["token"] and dat_token_cache["expires"] and now < dat_token_cache["expires"]:
        return dat_token_cache["token"]
    if DAT_CLIENT_ID == "demo":
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://identity.dat.com/access/oauth/token",
                data={"grant_type": "client_credentials", "client_id": DAT_CLIENT_ID, "client_secret": DAT_CLIENT_SECRET}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    dat_token_cache["token"] = data["access_token"]
                    dat_token_cache["expires"] = now + timedelta(seconds=data.get("expires_in", 3600) - 60)
                    return dat_token_cache["token"]
    except Exception as e:
        logger.error(f"DAT auth error: {e}")
    return None

async def fetch_loads(state_code: str) -> list:
    token = await get_dat_token()
    if not token:
        return get_demo_loads(state_code)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{DAT_BASE_URL}/loads/search",
                json={"origin": {"area": {"stateProv": state_code, "country": "US"}}, "equipmentType": "V", "pageSize": 20},
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return parse_dat_loads(data.get("loads", []), state_code)
    except Exception as e:
        logger.error(f"DAT fetch error: {e}")
    return get_demo_loads(state_code)

def parse_dat_loads(raw_loads, state_code):
    loads = []
    for item in raw_loads:
        origin = item.get("origin", {}).get("area", {})
        dest = item.get("destination", {}).get("area", {})
        rate_info = item.get("rateInfo", {})
        loads.append({
            "id": item.get("loadId", f"DAT-{hash(str(item))}"),
            "origin_city": origin.get("city", "Unknown"),
            "origin_state": origin.get("stateProv", state_code),
            "dest_city": dest.get("city", "Unknown"),
            "dest_state": dest.get("stateProv", "??"),
            "rate": rate_info.get("ratePerMile", 0),
            "total_rate": rate_info.get("totalRate", 0),
            "miles": item.get("tripMiles", 0),
            "weight": item.get("loadInfo", {}).get("weight", 0),
            "equipment": item.get("equipmentType", "V"),
            "broker": item.get("company", {}).get("name", "Unknown"),
            "mc_number": item.get("company", {}).get("mcNumber", ""),
            "posted": item.get("loadDateCreated", ""),
            "description": item.get("commodity", "General Freight"),
        })
    return loads

def get_demo_loads(state_code: str) -> list:
    import random
    cities = {
        "CA": ["Los Angeles", "San Francisco", "Fresno"],
        "TX": ["Dallas", "Houston", "San Antonio"],
        "FL": ["Miami", "Orlando", "Tampa"],
        "IL": ["Chicago", "Rockford"],
        "NY": ["New York", "Buffalo"],
    }
    dest_states = ["TX", "CA", "FL", "OH", "GA", "NC", "IL", "PA"]
    state_cities = cities.get(state_code, [US_STATES.get(state_code, state_code)])
    brokers = ["Coyote Logistics", "Echo Global", "CH Robinson", "Total Quality Logistics", "Landstar"]
    loads = []
    for i in range(random.randint(4, 8)):
        rate = round(random.uniform(1.8, 4.5), 2)
        miles = random.randint(200, 2000)
        loads.append({
            "id": f"DEMO-{state_code}-{i+1}-{datetime.now().strftime('%H%M%S')}",
            "origin_city": random.choice(state_cities),
            "origin_state": state_code,
            "dest_city": random.choice(["Charlotte", "Atlanta", "Phoenix", "Columbus", "Nashville"]),
            "dest_state": random.choice(dest_states),
            "rate": rate,
            "total_rate": round(rate * miles),
            "miles": miles,
            "weight": random.randint(20000, 45000),
            "equipment": random.choice(["V", "R", "F"]),
            "broker": random.choice(brokers),
            "mc_number": f"MC-{random.randint(100000, 999999)}",
            "posted": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "description": random.choice(["General Freight", "Auto Parts", "Electronics", "Food Grade"]),
        })
    return loads

def is_scam(load):
    if load["id"] in banned_loads:
        return True
    text = f"{load.get('description','')} {load.get('broker','')}".lower()
    for p in SCAM_PATTERNS:
        if re.search(p, text, re.IGNORECASE):
            return True
    if load.get("rate", 0) > 10.0:
        return True
    if not load.get("mc_number"):
        return True
    return False

def is_hot(load):
    if is_scam(load):
        return False
    return load.get("rate", 0) >= 3.0 or (load.get("rate", 0) >= 2.5 and load.get("miles", 0) > 1000) or load.get("origin_state", "") in HOT_STATES

def format_load(load, user_id):
    eq_map = {"V": "Van 🚐", "R": "Reefer ❄️", "F": "Flatbed 🏗️"}
    eq = eq_map.get(load.get("equipment", "V"), load.get("equipment", "V"))
    scam = is_scam(load)
    hot = is_hot(load)

    if scam:
        header = "🚫 *SCAM/FAKE LOAD*"
    elif hot:
        header = "🔥 *HOT LOAD*"
    else:
        header = "📦 *Load*"

    lines = [
        header,
        f"📍 *{load['origin_city']}, {load['origin_state']}* → *{load['dest_city']}, {load['dest_state']}*",
        f"🚛 {eq}  •  📏 {load.get('miles', 0):,} mi",
        f"💰 `${load.get('rate', 0):.2f}/mi`  •  Total: `${load.get('total_rate', 0):,}`",
        f"⚖️ {load.get('weight', 0):,} lbs",
        f"🏢 {load.get('broker', 'N/A')}  ({load.get('mc_number', 'No MC ⚠️')})",
        f"📦 {load.get('description', 'General')}",
        f"🕐 {load.get('posted', 'N/A')}",
    ]
    if scam:
        lines.append("\n⛔ *SCAM belgilari bor! Ehtiyot bo'ling!*")
    return "\n".join(lines)

def build_state_keyboard(user_id, page=0):
    selected = user_states.get(user_id, {}).get("selected_states", [])
    state_list = list(US_STATES.keys())
    page_size = 20
    start = page * page_size
    end = min(start + page_size, len(state_list))
    page_states = state_list[start:end]

    buttons = []
    row = []
    for i, code in enumerate(page_states):
        is_sel = code in selected
        is_h = code in HOT_STATES
        label = f"{'✅' if is_sel else ''}{'🔥' if is_h else ''} {code}"
        row.append(InlineKeyboardButton(label, callback_data=f"state_{code}"))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Oldingi", callback_data=f"page_{page-1}"))
    if end < len(state_list):
        nav.append(InlineKeyboardButton("Keyingi ▶️", callback_data=f"page_{page+1}"))
    if nav:
        buttons.append(nav)

    buttons.append([
        InlineKeyboardButton("✅ Tayyor / Done", callback_data="states_done"),
        InlineKeyboardButton("🗑 Tozalash", callback_data="states_clear")
    ])
    return InlineKeyboardMarkup(buttons)

# ─── HANDLERS ─────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in user_states:
        user_states[uid] = {"selected_states": [], "monitoring": False, "language": "uz"}
    await update.message.reply_text(t(uid, "welcome"), parse_mode="Markdown")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    lang = user_states.get(uid, {}).get("language", "uz")
    if lang == "uz":
        text = ("📖 *Qo'llanma*\n\n"
                "/states - Shtatlarni tanlash\n"
                "/loads - Yuklarni ko'rish\n"
                "/monitor on - Monitoring yoqish\n"
                "/monitor off - Monitoringni o'chirish\n"
                "/ban [load\\_id] - Yukni scam qilish\n"
                "/settings - Til o'zgartirish\n\n"
                "🔥 HOT = $3.00/mi+ yoki 1000+ mil\n"
                "🚫 SCAM = MC yo'q, avans to'lov, $10+/mi")
    else:
        text = ("📖 *Guide*\n\n"
                "/states - Select states\n"
                "/loads - View loads\n"
                "/monitor on - Enable monitoring\n"
                "/monitor off - Disable monitoring\n"
                "/ban [load\\_id] - Ban scam load\n"
                "/settings - Change language\n\n"
                "🔥 HOT = $3.00/mi+ or 1000+ miles\n"
                "🚫 SCAM = No MC, upfront fees, $10+/mi")
    await update.message.reply_text(text, parse_mode="Markdown")

async def states_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in user_states:
        user_states[uid] = {"selected_states": [], "monitoring": False, "language": "uz"}
    count = len(user_states[uid].get("selected_states", []))
    lang = user_states[uid].get("language", "uz")
    count_text = f"✅ {count} ta shtat tanlangan" if lang == "uz" else f"✅ {count} states selected"
    await update.message.reply_text(
        f"{t(uid, 'choose_state')}\n{count_text}",
        reply_markup=build_state_keyboard(uid, 0),
        parse_mode="Markdown"
    )

async def loads_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in user_states:
        user_states[uid] = {"selected_states": [], "monitoring": False, "language": "uz"}
    selected = user_states[uid].get("selected_states", [])
    if not selected:
        await update.message.reply_text(t(uid, "no_states"))
        return

    msg = await update.message.reply_text(t(uid, "loading"))
    all_loads = []
    for state in selected[:5]:
        loads = await fetch_loads(state)
        all_loads.extend(loads)

    if not all_loads:
        await msg.edit_text(t(uid, "no_loads"))
        return

    def sort_key(l):
        if is_scam(l): return 3
        if is_hot(l): return 1
        return 2
    all_loads.sort(key=sort_key)

    hot_count = sum(1 for l in all_loads if is_hot(l))
    scam_count = sum(1 for l in all_loads if is_scam(l))
    lang = user_states[uid].get("language", "uz")
    if lang == "uz":
        summary = f"📊 *{len(all_loads)} ta yuk topildi*\n🔥 HOT: {hot_count} | 🚫 SCAM: {scam_count}\n{'─'*25}"
    else:
        summary = f"📊 *{len(all_loads)} loads found*\n🔥 HOT: {hot_count} | 🚫 SCAM: {scam_count}\n{'─'*25}"
    await msg.edit_text(summary, parse_mode="Markdown")

    for load in all_loads[:10]:
        text = format_load(load, uid)
        keyboard = None
        if not is_scam(load):
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("🚫 Scam belgilash", callback_data=f"ban_{load['id']}")
            ]])
        try:
            await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
            await asyncio.sleep(0.3)
        except Exception as e:
            logger.error(f"Send error: {e}")

async def monitor_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in user_states:
        user_states[uid] = {"selected_states": [], "monitoring": False, "language": "uz"}
    args = context.args
    if args and args[0].lower() == "on":
        user_states[uid]["monitoring"] = True
        monitoring_users[uid] = user_states[uid].get("selected_states", [])
        await update.message.reply_text(t(uid, "monitoring_on"))
    elif args and args[0].lower() == "off":
        user_states[uid]["monitoring"] = False
        monitoring_users.pop(uid, None)
        await update.message.reply_text(t(uid, "monitoring_off"))
    else:
        is_on = user_states[uid].get("monitoring", False)
        lang = user_states[uid].get("language", "uz")
        status = "✅ YOQIQ" if is_on else "⛔ O'CHIQ"
        states = user_states[uid].get("selected_states", [])
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Yoqish", callback_data="mon_on"),
            InlineKeyboardButton("⛔ O'chirish", callback_data="mon_off"),
        ]])
        text = f"🔴 Monitoring: {status}\n📍 {', '.join(states) if states else 'Tanlanmagan'}"
        await update.message.reply_text(text, reply_markup=keyboard)

async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not context.args:
        await update.message.reply_text("Ishlatish: `/ban [load_id]`", parse_mode="Markdown")
        return
    load_id = context.args[0]
    banned_loads.add(load_id)
    await update.message.reply_text(f"🚫 Load banned: `{load_id}`", parse_mode="Markdown")

async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🇺🇿 O'zbek", callback_data="lang_uz"),
        InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
    ]])
    await update.message.reply_text("🌐 *Til / Language:*", reply_markup=keyboard, parse_mode="Markdown")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    data = query.data
    if uid not in user_states:
        user_states[uid] = {"selected_states": [], "monitoring": False, "language": "uz"}
    await query.answer()

    if data.startswith("state_"):
        code = data[6:]
        selected = user_states[uid].setdefault("selected_states", [])
        if code in selected:
            selected.remove(code)
        else:
            if len(selected) >= 10:
                await query.answer("⚠️ Max 10 shtat!", show_alert=True)
                return
            selected.append(code)
        count = len(selected)
        lang = user_states[uid].get("language", "uz")
        count_text = f"✅ {count} ta tanlangan" if lang == "uz" else f"✅ {count} selected"
        await query.edit_message_text(
            f"{t(uid, 'choose_state')}\n{count_text}",
            reply_markup=build_state_keyboard(uid, 0),
            parse_mode="Markdown"
        )

    elif data.startswith("page_"):
        page = int(data[5:])
        count = len(user_states[uid].get("selected_states", []))
        lang = user_states[uid].get("language", "uz")
        count_text = f"✅ {count} ta tanlangan" if lang == "uz" else f"✅ {count} selected"
        await query.edit_message_text(
            f"{t(uid, 'choose_state')}\n{count_text}",
            reply_markup=build_state_keyboard(uid, page),
            parse_mode="Markdown"
        )

    elif data == "states_done":
        selected = user_states[uid].get("selected_states", [])
        lang = user_states[uid].get("language", "uz")
        if lang == "uz":
            msg = f"✅ *{len(selected)} ta shtat saqlandi:*\n`{', '.join(selected)}`\n\n/loads buyrug'i bilan yuklarni ko'ring!"
        else:
            msg = f"✅ *{len(selected)} states saved:*\n`{', '.join(selected)}`\n\nUse /loads to view freight!"
        await query.edit_message_text(msg, parse_mode="Markdown")

    elif data == "states_clear":
        user_states[uid]["selected_states"] = []
        await query.edit_message_text(
            f"{t(uid, 'choose_state')}\n✅ 0 tanlangan",
            reply_markup=build_state_keyboard(uid, 0),
            parse_mode="Markdown"
        )

    elif data.startswith("ban_"):
        load_id = data[4:]
        banned_loads.add(load_id)
        await query.edit_message_text(f"🚫 *Banned:* `{load_id}`", parse_mode="Markdown")

    elif data == "mon_on":
        user_states[uid]["monitoring"] = True
        monitoring_users[uid] = user_states[uid].get("selected_states", [])
        await query.edit_message_text(t(uid, "monitoring_on"))

    elif data == "mon_off":
        user_states[uid]["monitoring"] = False
        monitoring_users.pop(uid, None)
        await query.edit_message_text(t(uid, "monitoring_off"))

    elif data.startswith("lang_"):
        lang = data[5:]
        user_states[uid]["language"] = lang
        name = "O'zbek tili 🇺🇿" if lang == "uz" else "English 🇬🇧"
        await query.edit_message_text(f"✅ *{name}*", parse_mode="Markdown")

# ─── MONITORING JOB ───────────────────────────────────────────────────────────
async def monitoring_job(app):
    if not monitoring_users:
        return
    for uid, states in list(monitoring_users.items()):
        if not states:
            continue
        for state in states[:3]:
            try:
                loads = await fetch_loads(state)
                new_hot = [l for l in loads if is_hot(l) and l["id"] not in sent_load_ids]
                for load in new_hot[:2]:
                    sent_load_ids.add(load["id"])
                    lang = user_states.get(uid, {}).get("language", "uz")
                    prefix = "🔥 *Yangi HOT yuk!*\n\n" if lang == "uz" else "🔥 *New HOT Load!*\n\n"
                    await app.bot.send_message(uid, prefix + format_load(load, uid), parse_mode="Markdown")
                    await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Monitor error {uid}: {e}")
    if len(sent_load_ids) > 1000:
        old = list(sent_load_ids)[:500]
        for i in old:
            sent_load_ids.discard(i)

# ─── MAIN — Python 3.12 compatible ───────────────────────────────────────────
async def main():
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN not set!")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("states", states_cmd))
    app.add_handler(CommandHandler("loads", loads_cmd))
    app.add_handler(CommandHandler("monitor", monitor_cmd))
    app.add_handler(CommandHandler("ban", ban_cmd))
    app.add_handler(CommandHandler("settings", settings_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(monitoring_job, "interval", minutes=5, args=[app])
    scheduler.start()

    logger.info("🚛 Freight Bot started!")

    # Python 3.12 compatible — use run_polling directly (no asyncio.run wrapper)
    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)

    # Keep running
    try:
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

if __name__ == "__main__":
    asyncio.run(main())

