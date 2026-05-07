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
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN")
DAT_CLIENT_ID  = os.getenv("DAT_CLIENT_ID", "YOUR_DAT_CLIENT_ID")
DAT_CLIENT_SECRET = os.getenv("DAT_CLIENT_SECRET", "YOUR_DAT_CLIENT_SECRET")
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

# HOT states (high demand freight corridors)
HOT_STATES = {"CA", "TX", "FL", "IL", "OH", "GA", "NC", "PA", "TN", "AZ"}

# Known scam/fake broker patterns
SCAM_PATTERNS = [
    r'\b(advance|upfront)\s+fee\b',
    r'\bpay\s+first\b',
    r'\bno\s+mc\s+number\b',
    r'\bwestern\s+union\b',
    r'\bzelle\s+only\b',
    r'\bcash\s+app\s+only\b',
    r'\btoo\s+good\s+to\s+be\s+true\b',
    r'\bno\s+insurance\b',
]

# ─── IN-MEMORY STORAGE ────────────────────────────────────────────────────────
user_states = {}       # user_id -> {"selected_states": [...], "monitoring": bool, "language": "uz/en"}
banned_loads = set()   # load_ids that are banned/scam
monitoring_users = {}  # user_id -> list of states to monitor
dat_token_cache = {"token": None, "expires": None}

# ─── TRANSLATIONS ─────────────────────────────────────────────────────────────
TEXTS = {
    "uz": {
        "welcome": "🚛 *Freight Broker Bot ga xush kelibsiz!*\n\nAmerika bo'ylab yuklarni kuzating, HOT yuklarni toping va scam brokerlardan himoyalaning!\n\n📍 /states - Shtat tanlash\n📊 /loads - Yuklarni ko'rish\n🔴 /monitor - Monitoring yoqish\n⚙️ /settings - Sozlamalar\n❓ /help - Yordam",
        "choose_state": "📍 *Shtat tanlang:*\nKuzatmoqchi bo'lgan shtatlarni belgilang:",
        "no_states": "⚠️ Hech qanday shtat tanlanmagan. /states buyrug'i bilan shtat tanlang.",
        "monitoring_on": "✅ Monitoring yoqildi! Yangi yuklar paydo bo'lganda xabar olasiz.",
        "monitoring_off": "⛔ Monitoring o'chirildi.",
        "hot_label": "🔥 HOT",
        "scam_label": "🚫 SCAM/FAKE",
        "banned": "🚫 Bu yuk SCAM sifatida belgilandi va ban qilindi!",
        "no_loads": "📭 Hozir bu shtatda yuk topilmadi.",
        "loading": "⏳ Yuklar qidirilmoqda...",
        "rate_per_mile": "$/mil",
        "settings_lang": "🌐 Til: O'zbek | English",
    },
    "en": {
        "welcome": "🚛 *Welcome to Freight Broker Bot!*\n\nMonitor loads across the US, find HOT loads and protect yourself from fake brokers!\n\n📍 /states - Select states\n📊 /loads - View loads\n🔴 /monitor - Enable monitoring\n⚙️ /settings - Settings\n❓ /help - Help",
        "choose_state": "📍 *Select State:*\nChoose the states you want to monitor:",
        "no_states": "⚠️ No states selected. Use /states to select states.",
        "monitoring_on": "✅ Monitoring enabled! You'll be notified when new loads appear.",
        "monitoring_off": "⛔ Monitoring disabled.",
        "hot_label": "🔥 HOT",
        "scam_label": "🚫 SCAM/FAKE",
        "banned": "🚫 This load has been flagged as SCAM and banned!",
        "no_loads": "📭 No loads found in this state right now.",
        "loading": "⏳ Searching for loads...",
        "rate_per_mile": "$/mi",
        "settings_lang": "🌐 Language: O'zbek | English",
    }
}

def t(user_id, key):
    lang = user_states.get(user_id, {}).get("language", "uz")
    return TEXTS[lang].get(key, TEXTS["en"][key])

# ─── DAT API ──────────────────────────────────────────────────────────────────
async def get_dat_token():
    """Get or refresh DAT OAuth token"""
    now = datetime.utcnow()
    if dat_token_cache["token"] and dat_token_cache["expires"] and now < dat_token_cache["expires"]:
        return dat_token_cache["token"]

    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://identity.dat.com/access/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": DAT_CLIENT_ID,
                "client_secret": DAT_CLIENT_SECRET,
            }
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                dat_token_cache["token"] = data["access_token"]
                dat_token_cache["expires"] = now + timedelta(seconds=data.get("expires_in", 3600) - 60)
                return dat_token_cache["token"]
            else:
                logger.error(f"DAT auth failed: {resp.status}")
                return None

async def fetch_loads_from_dat(state_code: str) -> list:
    """Fetch loads from DAT for a given state"""
    token = await get_dat_token()
    if not token:
        return get_demo_loads(state_code)  # fallback to demo

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    payload = {
        "origin": {
            "area": {
                "stateProv": state_code,
                "country": "US"
            }
        },
        "equipmentType": "V",  # Van
        "includeLoadsWithoutLength": True,
        "includeLoadsWithoutWeight": True,
        "pageSize": 20
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{DAT_BASE_URL}/loads/search",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return parse_dat_loads(data.get("loads", []), state_code)
                else:
                    logger.warning(f"DAT API error {resp.status}, using demo data")
                    return get_demo_loads(state_code)
    except Exception as e:
        logger.error(f"DAT fetch error: {e}")
        return get_demo_loads(state_code)

def parse_dat_loads(raw_loads: list, state_code: str) -> list:
    """Parse DAT API response into our format"""
    loads = []
    for item in raw_loads:
        origin = item.get("origin", {}).get("area", {})
        dest = item.get("destination", {}).get("area", {})
        rate_info = item.get("rateInfo", {})

        load = {
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
            "broker": item.get("company", {}).get("name", "Unknown Broker"),
            "mc_number": item.get("company", {}).get("mcNumber", ""),
            "posted": item.get("loadDateCreated", ""),
            "description": item.get("commodity", "General Freight"),
            "source": "DAT"
        }
        loads.append(load)
    return loads

def get_demo_loads(state_code: str) -> list:
    """Demo loads when API not configured"""
    import random
    cities = {
        "CA": ["Los Angeles", "San Francisco", "Fresno"],
        "TX": ["Dallas", "Houston", "San Antonio"],
        "FL": ["Miami", "Orlando", "Tampa"],
        "IL": ["Chicago", "Rockford", "Peoria"],
        "NY": ["New York", "Buffalo", "Albany"],
    }
    dest_states = ["TX", "CA", "FL", "OH", "GA", "NC", "IL", "PA"]
    state_cities = cities.get(state_code, [f"{US_STATES.get(state_code, state_code)} City"])

    loads = []
    for i in range(random.randint(4, 8)):
        rate = round(random.uniform(1.8, 4.5), 2)
        miles = random.randint(200, 2000)
        loads.append({
            "id": f"DEMO-{state_code}-{i+1}-{datetime.now().strftime('%H%M%S')}",
            "origin_city": random.choice(state_cities),
            "origin_state": state_code,
            "dest_city": f"{random.choice(['Charlotte','Atlanta','Phoenix','Columbus','Nashville'])}",
            "dest_state": random.choice(dest_states),
            "rate": rate,
            "total_rate": round(rate * miles),
            "miles": miles,
            "weight": random.randint(20000, 45000),
            "equipment": random.choice(["V", "R", "F"]),
            "broker": random.choice(["Coyote Logistics", "Echo Global", "CH Robinson", "Total Quality Logistics", "Landstar"]),
            "mc_number": f"MC-{random.randint(100000, 999999)}",
            "posted": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "description": random.choice(["General Freight", "Auto Parts", "Electronics", "Food Grade", "Building Materials"]),
            "source": "DEMO"
        })
    return loads

# ─── SCAM DETECTION ───────────────────────────────────────────────────────────
def is_scam_load(load: dict) -> bool:
    """Check if load has scam indicators"""
    if load["id"] in banned_loads:
        return True

    text_to_check = f"{load.get('description', '')} {load.get('broker', '')}".lower()
    for pattern in SCAM_PATTERNS:
        if re.search(pattern, text_to_check, re.IGNORECASE):
            return True

    # Suspicious rate (too high)
    if load.get("rate", 0) > 10.0:
        return True

    # No MC number
    if not load.get("mc_number"):
        return True

    return False

def is_hot_load(load: dict) -> bool:
    """Check if load is HOT (high value/demand)"""
    rate = load.get("rate", 0)
    miles = load.get("miles", 0)
    origin_state = load.get("origin_state", "")
    return (
        rate >= 3.0 or
        (rate >= 2.5 and miles > 1000) or
        origin_state in HOT_STATES
    )

# ─── LOAD FORMATTER ───────────────────────────────────────────────────────────
def format_load(load: dict, user_id: int) -> str:
    scam = is_scam_load(load)
    hot = is_hot_load(load) and not scam

    if scam:
        header = f"🚫 *SCAM/FAKE LOAD*\n"
    elif hot:
        header = f"🔥 *HOT LOAD*\n"
    else:
        header = f"📦 *Load*\n"

    eq_map = {"V": "Van 🚐", "R": "Reefer ❄️", "F": "Flatbed 🏗️", "SD": "Step Deck", "DD": "Double Drop"}
    equipment = eq_map.get(load.get("equipment", "V"), load.get("equipment", "V"))

    rpm = load.get('rate', 0)
    total = load.get('total_rate', 0)

    lines = [
        header,
        f"📍 *{load['origin_city']}, {load['origin_state']}* → *{load['dest_city']}, {load['dest_state']}*",
        f"🚛 {equipment}  •  📏 {load.get('miles', 0):,} mi",
        f"💰 `${rpm:.2f}/mi`  •  Total: `${total:,}`",
        f"⚖️ {load.get('weight', 0):,} lbs",
        f"🏢 {load.get('broker', 'N/A')}  ({load.get('mc_number', 'No MC ⚠️')})",
        f"📦 {load.get('description', 'General')}",
        f"🕐 {load.get('posted', 'N/A')}",
    ]

    if scam:
        lines.append("\n⛔ *Bu yuk SCAM belgilari ko'rsatmoqda! Ehtiyot bo'ling!*")

    return "\n".join(lines)

# ─── STATE SELECTION KEYBOARD ─────────────────────────────────────────────────
def build_state_keyboard(user_id: int, page: int = 0):
    user_data = user_states.get(user_id, {"selected_states": [], "language": "uz"})
    selected = user_data.get("selected_states", [])

    state_list = list(US_STATES.keys())
    page_size = 20
    start = page * page_size
    end = min(start + page_size, len(state_list))
    page_states = state_list[start:end]

    buttons = []
    row = []
    for i, code in enumerate(page_states):
        is_selected = code in selected
        is_hot = code in HOT_STATES
        label = f"{'✅' if is_selected else ''}{'🔥' if is_hot else ''} {code}"
        row.append(InlineKeyboardButton(label, callback_data=f"state_{code}"))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    # Navigation
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

# ─── COMMAND HANDLERS ─────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_states:
        user_states[user_id] = {"selected_states": [], "monitoring": False, "language": "uz"}

    await update.message.reply_text(
        t(user_id, "welcome"),
        parse_mode="Markdown"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = user_states.get(user_id, {}).get("language", "uz")

    if lang == "uz":
        text = (
            "📖 *Bot Qo'llanmasi*\n\n"
            "1️⃣ `/states` - Kuzatmoqchi bo'lgan shtatlarni tanlang\n"
            "2️⃣ `/loads` - Tanlangan shtatlardagi yuklarni ko'ring\n"
            "3️⃣ `/monitor on` - Avtomatik monitoring yoqing\n"
            "4️⃣ `/monitor off` - Monitoringni o'chiring\n"
            "5️⃣ `/ban [load_id]` - Yuk ID ni scam sifatida ban qiling\n"
            "6️⃣ `/settings` - Tilni o'zgartiring\n\n"
            "🔥 *HOT yuk* = $3.00/mi dan yuqori yoki 1000+ mil\n"
            "🚫 *SCAM yuk* = MC raqami yo'q, avans to'lov, shubhali narx\n"
            "📊 Demo rejim: DAT API sozlanmagan bo'lsa demo data ko'rsatiladi"
        )
    else:
        text = (
            "📖 *Bot Guide*\n\n"
            "1️⃣ `/states` - Select states to monitor\n"
            "2️⃣ `/loads` - View loads in selected states\n"
            "3️⃣ `/monitor on` - Enable auto monitoring\n"
            "4️⃣ `/monitor off` - Disable monitoring\n"
            "5️⃣ `/ban [load_id]` - Ban a load as scam\n"
            "6️⃣ `/settings` - Change language\n\n"
            "🔥 *HOT load* = $3.00+/mi or 1000+ miles\n"
            "🚫 *SCAM load* = No MC number, upfront fees, suspicious rate\n"
            "📊 Demo mode: Demo data shown when DAT API not configured"
        )

    await update.message.reply_text(text, parse_mode="Markdown")

async def states_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_states:
        user_states[user_id] = {"selected_states": [], "monitoring": False, "language": "uz"}

    selected = user_states[user_id].get("selected_states", [])
    count_text = f"✅ {len(selected)} ta shtat tanlangan" if user_states[user_id].get("language") == "uz" else f"✅ {len(selected)} states selected"

    await update.message.reply_text(
        f"{t(user_id, 'choose_state')}\n{count_text}",
        reply_markup=build_state_keyboard(user_id, 0),
        parse_mode="Markdown"
    )

async def loads_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_states:
        user_states[user_id] = {"selected_states": [], "monitoring": False, "language": "uz"}

    selected = user_states[user_id].get("selected_states", [])
    if not selected:
        await update.message.reply_text(t(user_id, "no_states"))
        return

    msg = await update.message.reply_text(t(user_id, "loading"))

    all_loads = []
    for state in selected[:5]:  # Max 5 states at once
        loads = await fetch_loads_from_dat(state)
        all_loads.extend(loads)

    if not all_loads:
        await msg.edit_text(t(user_id, "no_loads"))
        return

    # Sort: scam last, hot first
    def sort_key(l):
        if is_scam_load(l): return 3
        if is_hot_load(l): return 1
        return 2

    all_loads.sort(key=sort_key)

    # Summary
    hot_count = sum(1 for l in all_loads if is_hot_load(l) and not is_scam_load(l))
    scam_count = sum(1 for l in all_loads if is_scam_load(l))
    lang = user_states[user_id].get("language", "uz")

    if lang == "uz":
        summary = f"📊 *{len(all_loads)} ta yuk topildi*\n🔥 HOT: {hot_count} | 🚫 SCAM: {scam_count}\n{'─'*30}\n"
    else:
        summary = f"📊 *{len(all_loads)} loads found*\n🔥 HOT: {hot_count} | 🚫 SCAM: {scam_count}\n{'─'*30}\n"

    await msg.edit_text(summary, parse_mode="Markdown")

    # Send each load (max 10)
    for load in all_loads[:10]:
        text = format_load(load, user_id)
        keyboard = None

        if not is_scam_load(load):
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("🚫 Scam deb belgilash", callback_data=f"ban_{load['id']}"),
                InlineKeyboardButton("📋 Nusxa olish", callback_data=f"copy_{load['id']}")
            ]])

        try:
            await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
            await asyncio.sleep(0.3)
        except Exception as e:
            logger.error(f"Error sending load: {e}")

async def monitor_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_states:
        user_states[user_id] = {"selected_states": [], "monitoring": False, "language": "uz"}

    args = context.args
    if args and args[0].lower() == "on":
        user_states[user_id]["monitoring"] = True
        monitoring_users[user_id] = user_states[user_id].get("selected_states", [])
        await update.message.reply_text(t(user_id, "monitoring_on"))
    elif args and args[0].lower() == "off":
        user_states[user_id]["monitoring"] = False
        monitoring_users.pop(user_id, None)
        await update.message.reply_text(t(user_id, "monitoring_off"))
    else:
        is_on = user_states[user_id].get("monitoring", False)
        lang = user_states[user_id].get("language", "uz")
        status = "✅ YOQIQ" if is_on else "⛔ O'CHIQ"
        states = user_states[user_id].get("selected_states", [])
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Yoqish / Turn ON", callback_data="mon_on"),
            InlineKeyboardButton("⛔ O'chirish / Turn OFF", callback_data="mon_off"),
        ]])
        if lang == "uz":
            text = f"🔴 *Monitoring holati:* {status}\n📍 Shtatlar: {', '.join(states) if states else 'Tanlanmagan'}"
        else:
            text = f"🔴 *Monitoring status:* {status}\n📍 States: {', '.join(states) if states else 'None selected'}"
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)

async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        lang = user_states.get(user_id, {}).get("language", "uz")
        msg = "Ishlatish: `/ban [load_id]`" if lang == "uz" else "Usage: `/ban [load_id]`"
        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    load_id = context.args[0]
    banned_loads.add(load_id)
    await update.message.reply_text(t(user_id, "banned"))

async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_states:
        user_states[user_id] = {"selected_states": [], "monitoring": False, "language": "uz"}

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🇺🇿 O'zbek tili", callback_data="lang_uz"),
        InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
    ]])
    await update.message.reply_text("🌐 *Til / Language:*", reply_markup=keyboard, parse_mode="Markdown")

# ─── CALLBACK HANDLERS ────────────────────────────────────────────────────────
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if user_id not in user_states:
        user_states[user_id] = {"selected_states": [], "monitoring": False, "language": "uz"}

    await query.answer()

    # State selection
    if data.startswith("state_"):
        code = data[6:]
        selected = user_states[user_id].setdefault("selected_states", [])
        if code in selected:
            selected.remove(code)
        else:
            if len(selected) < 10:
                selected.append(code)
            else:
                lang = user_states[user_id].get("language", "uz")
                msg = "⚠️ Maksimum 10 ta shtat tanlash mumkin!" if lang == "uz" else "⚠️ Maximum 10 states allowed!"
                await query.answer(msg, show_alert=True)
                return

        current_page = 0
        try:
            # Extract page from current keyboard
            for row in query.message.reply_markup.inline_keyboard:
                for btn in row:
                    if "page_" in btn.callback_data:
                        current_page = int(btn.callback_data.split("_")[1])
                        break
        except:
            pass

        count = len(user_states[user_id]["selected_states"])
        lang = user_states[user_id].get("language", "uz")
        count_text = f"✅ {count} ta shtat tanlangan" if lang == "uz" else f"✅ {count} states selected"

        await query.edit_message_text(
            f"{t(user_id, 'choose_state')}\n{count_text}",
            reply_markup=build_state_keyboard(user_id, current_page),
            parse_mode="Markdown"
        )

    elif data.startswith("page_"):
        page = int(data[5:])
        count = len(user_states[user_id].get("selected_states", []))
        lang = user_states[user_id].get("language", "uz")
        count_text = f"✅ {count} ta shtat tanlangan" if lang == "uz" else f"✅ {count} states selected"
        await query.edit_message_text(
            f"{t(user_id, 'choose_state')}\n{count_text}",
            reply_markup=build_state_keyboard(user_id, page),
            parse_mode="Markdown"
        )

    elif data == "states_done":
        selected = user_states[user_id].get("selected_states", [])
        lang = user_states[user_id].get("language", "uz")
        if lang == "uz":
            msg = f"✅ *{len(selected)} ta shtat saqlandi:*\n`{', '.join(selected)}`\n\n/loads buyrug'i bilan yuklarni ko'ring!"
        else:
            msg = f"✅ *{len(selected)} states saved:*\n`{', '.join(selected)}`\n\nUse /loads to view freight!"
        await query.edit_message_text(msg, parse_mode="Markdown")

    elif data == "states_clear":
        user_states[user_id]["selected_states"] = []
        lang = user_states[user_id].get("language", "uz")
        count_text = "✅ 0 ta shtat tanlangan" if lang == "uz" else "✅ 0 states selected"
        await query.edit_message_text(
            f"{t(user_id, 'choose_state')}\n{count_text}",
            reply_markup=build_state_keyboard(user_id, 0),
            parse_mode="Markdown"
        )

    elif data.startswith("ban_"):
        load_id = data[4:]
        banned_loads.add(load_id)
        await query.edit_message_text(f"🚫 *Load banned!*\nID: `{load_id}`", parse_mode="Markdown")

    elif data == "mon_on":
        user_states[user_id]["monitoring"] = True
        monitoring_users[user_id] = user_states[user_id].get("selected_states", [])
        await query.edit_message_text(t(user_id, "monitoring_on"))

    elif data == "mon_off":
        user_states[user_id]["monitoring"] = False
        monitoring_users.pop(user_id, None)
        await query.edit_message_text(t(user_id, "monitoring_off"))

    elif data.startswith("lang_"):
        lang = data[5:]
        user_states[user_id]["language"] = lang
        flag = "🇺🇿" if lang == "uz" else "🇬🇧"
        name = "O'zbek tili" if lang == "uz" else "English"
        await query.edit_message_text(f"{flag} Til o'zgartirildi: *{name}*", parse_mode="Markdown")

# ─── MONITORING SCHEDULER ─────────────────────────────────────────────────────
sent_load_ids = set()  # Track already sent loads

async def monitoring_job(app):
    """Run every 5 minutes - check for new loads"""
    if not monitoring_users:
        return

    for user_id, states in list(monitoring_users.items()):
        if not states:
            continue

        for state in states[:3]:  # Check max 3 states per cycle
            try:
                loads = await fetch_loads_from_dat(state)
                new_hot = [l for l in loads if is_hot_load(l) and not is_scam_load(l) and l["id"] not in sent_load_ids]

                for load in new_hot[:3]:  # Max 3 notifications
                    sent_load_ids.add(load["id"])
                    lang = user_states.get(user_id, {}).get("language", "uz")
                    prefix = "🔥 *Yangi HOT yuk topildi!*\n\n" if lang == "uz" else "🔥 *New HOT load found!*\n\n"
                    text = prefix + format_load(load, user_id)
                    await app.bot.send_message(user_id, text, parse_mode="Markdown")
                    await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"Monitoring error for user {user_id}: {e}")

    # Clean up old IDs (keep last 1000)
    if len(sent_load_ids) > 1000:
        old = list(sent_load_ids)[:500]
        for i in old:
            sent_load_ids.discard(i)

# ─── MAIN ─────────────────────────────────────────────────────────────────────
async def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("states", states_cmd))
    app.add_handler(CommandHandler("loads", loads_cmd))
    app.add_handler(CommandHandler("monitor", monitor_cmd))
    app.add_handler(CommandHandler("ban", ban_cmd))
    app.add_handler(CommandHandler("settings", settings_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(monitoring_job, "interval", minutes=5, args=[app])
    scheduler.start()

    logger.info("🚛 Freight Bot started!")
    await app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    asyncio.run(main())
