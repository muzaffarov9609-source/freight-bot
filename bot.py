import os
import logging
import asyncio
import json
import random
from datetime import datetime, timedelta
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)
 
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
 
TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "")  # optional: @yourchannel
 
# ─── In-memory storage ───────────────────────────────────────────────
user_data = {}          # {user_id: {states, trailers, history, stats}}
load_history = []       # global load history
broker_ratings = {}     # {mc_number: {rating, reports, name}}
 
TRAILER_TYPES = {
    "VAN":      "Van / Dry Van",
    "FLATBED":  "Flatbed",
    "STEPDECK": "Step Deck",
    "REEFER":   "Reefer",
    "HOTSHOT":  "Hot Shot",
    "LOWBOY":   "Lowboy",
    "TANKER":   "Tanker",
    "POWER":    "Power Only",
}
 
US_STATES = [
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA",
    "HI","ID","IL","IN","IA","KS","KY","LA","ME","MD",
    "MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC",
    "SD","TN","TX","UT","VT","VA","WA","WV","WI","WY"
]
 
SCAM_KEYWORDS = ["upfront payment","advance fee","zelle only","cashapp only",
                  "no mc","no dot","wire first","bitcoin payment"]
 
# ─── Demo data generator ─────────────────────────────────────────────
def generate_demo_loads(states, trailers, count=12):
    loads = []
    cities = {
        "CA":["Los Angeles","Fresno","San Diego"],
        "TX":["Dallas","Houston","San Antonio"],
        "FL":["Miami","Tampa","Orlando"],
        "NY":["New York","Buffalo","Albany"],
        "IL":["Chicago","Rockford","Peoria"],
        "GA":["Atlanta","Savannah","Augusta"],
        "OH":["Columbus","Cleveland","Cincinnati"],
        "PA":["Philadelphia","Pittsburgh","Allentown"],
        "WA":["Seattle","Spokane","Tacoma"],
        "AZ":["Phoenix","Tucson","Mesa"],
        "CO":["Denver","Colorado Springs","Boulder"],
        "MN":["Minneapolis","St Paul","Duluth"],
    }
    brokers = [
        {"name":"Echo Global Logistics","mc":"MC-257866","phone":"800-354-7993","email":"loads@echo.com","rating":4.5},
        {"name":"Coyote Logistics","mc":"MC-345443","phone":"888-264-9683","email":"ops@coyote.com","rating":4.2},
        {"name":"XPO Logistics","mc":"MC-378697","phone":"800-755-2728","email":"freight@xpo.com","rating":4.0},
        {"name":"CH Robinson","mc":"MC-154704","phone":"800-323-7587","email":"info@chrobinson.com","rating":4.7},
        {"name":"TQL (Total Quality Logistics)","mc":"MC-488465","phone":"800-580-3101","email":"tql@tql.com","rating":4.3},
        {"name":"Landstar System","mc":"MC-219480","phone":"800-872-9400","email":"ops@landstar.com","rating":4.6},
        {"name":"FastFreight LLC","mc":"","phone":"555-000-1234","email":"","rating":1.0},  # scam
    ]
 
    for i in range(count):
        origin_state = random.choice(states)
        dest_state   = random.choice(US_STATES)
        origin_city  = random.choice(cities.get(origin_state, [origin_state + " City"]))
        dest_city    = random.choice(cities.get(dest_state,   [dest_state   + " City"]))
        miles        = random.randint(200, 2500)
        rate_per_mi  = round(random.uniform(1.80, 4.50), 2)
        total_rate   = int(miles * rate_per_mi)
        weight       = random.randint(10000, 44000)
        trailer      = random.choice(trailers) if trailers else random.choice(list(TRAILER_TYPES.keys()))
        broker       = random.choice(brokers)
        pickup_date  = (datetime.now() + timedelta(days=random.randint(0, 3))).strftime("%m/%d/%Y")
 
        loads.append({
            "id":          f"L{random.randint(10000,99999)}",
            "origin":      f"{origin_city}, {origin_state}",
            "dest":        f"{dest_city}, {dest_state}",
            "miles":       miles,
            "rate":        total_rate,
            "rate_per_mi": rate_per_mi,
            "weight":      weight,
            "trailer":     trailer,
            "broker":      broker,
            "pickup":      pickup_date,
            "timestamp":   datetime.now(),
        })
    return loads
 
# ─── Helpers ─────────────────────────────────────────────────────────
def get_user(uid):
    if uid not in user_data:
        user_data[uid] = {
            "states":   [],
            "trailers": [],
            "history":  [],
            "stats":    {"loads_viewed": 0, "hot_found": 0, "scams_blocked": 0},
            "monitor":  False,
            "lang":     "uz",
        }
    return user_data[uid]
 
def is_hot(load):
    return load["rate_per_mi"] >= 3.0 or load["miles"] >= 1000
 
def is_scam(load):
    broker = load["broker"]
    if not broker.get("mc"):
        return True, "MC raqami yo'q"
    desc = (broker.get("email","") + broker.get("name","")).lower()
    for kw in SCAM_KEYWORDS:
        if kw in desc:
            return True, f"Shubhali kalit so'z: {kw}"
    if broker.get("rating", 5) < 2.0:
        return True, "Juda past reyting"
    return False, ""
 
def broker_ai_score(broker):
    score = broker.get("rating", 3.0) * 20  # 0-100
    if not broker.get("mc"):       score -= 40
    if not broker.get("email"):    score -= 10
    if not broker.get("phone"):    score -= 10
    return max(0, min(100, int(score)))
 
def fmt_load(load, idx):
    hot_tag  = "🔥 HOT | " if is_hot(load) else ""
    scam, reason = is_scam(load)
    if scam:
        return (f"🚫 *#{idx} SCAM/FAKE* — {reason}\n"
                f"   {load['origin']} → {load['dest']}\n"
                f"   Broker: {load['broker']['name']}\n")
    b = load["broker"]
    ai = broker_ai_score(b)
    ai_emoji = "🟢" if ai>=70 else "🟡" if ai>=40 else "🔴"
    return (
        f"{hot_tag}*#{idx} {load['trailer']} | {load['id']}*\n"
        f"📍 {load['origin']} → {load['dest']}\n"
        f"📏 {load['miles']:,} mil\n"
        f"💰 ${load['rate']:,}  (${load['rate_per_mi']}/mil)\n"
        f"⚖️ {load['weight']:,} lbs\n"
        f"📅 Pickup: {load['pickup']}\n"
        f"🏢 *{b['name']}* | {b['mc'] or '—'}\n"
        f"📞 {b.get('phone','—')}  ✉️ {b.get('email','—')}\n"
        f"{ai_emoji} Broker AI Score: {ai}/100\n"
    )
 
# ─── /start ──────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    get_user(uid)
    text = (
        "🚛 *Freight Monitor Bot*\n\n"
        "Xush kelibsiz! Boshlash uchun:\n\n"
        "1️⃣ /trailer — Trailer turini tanlang\n"
        "2️⃣ /states  — Shtatlarni tanlang\n"
        "3️⃣ /loads   — Yuklarni ko'ring\n\n"
        "📌 Boshqa buyruqlar:\n"
        "/monitor on — Avtomatik kuzatuv\n"
        "/stats      — Statistika\n"
        "/rates      — Narx tahlili\n"
        "/help       — Yordam\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")
 
# ─── /trailer ────────────────────────────────────────────────────────
async def trailer_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u   = get_user(uid)
    keyboard = []
    row = []
    for code, label in TRAILER_TYPES.items():
        chk = "✅ " if code in u["trailers"] else ""
        row.append(InlineKeyboardButton(f"{chk}{label}", callback_data=f"TR_{code}"))
        if len(row) == 2:
            keyboard.append(row); row = []
    if row: keyboard.append(row)
    keyboard.append([
        InlineKeyboardButton("🗑 Hammasini tozala", callback_data="TR_CLEAR"),
        InlineKeyboardButton("✅ Tayyor",            callback_data="TR_DONE"),
    ])
    sel = ", ".join(u["trailers"]) if u["trailers"] else "hech biri"
    await update.message.reply_text(
        f"🚛 *Trailer turini tanlang* (hozir: {sel})\nBir nechta tanlash mumkin:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
 
async def trailer_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q   = update.callback_query; await q.answer()
    uid = q.from_user.id
    u   = get_user(uid)
    code = q.data.replace("TR_","")
    if code == "CLEAR":
        u["trailers"] = []
    elif code == "DONE":
        sel = ", ".join(u["trailers"]) if u["trailers"] else "barchasi"
        await q.edit_message_text(f"✅ Trailer tanlandi: *{sel}*\nEndi /states bilan shtatlarni tanlang.", parse_mode="Markdown")
        return
    else:
        if code in u["trailers"]: u["trailers"].remove(code)
        else: u["trailers"].append(code)
 
    keyboard = []
    row = []
    for c, label in TRAILER_TYPES.items():
        chk = "✅ " if c in u["trailers"] else ""
        row.append(InlineKeyboardButton(f"{chk}{label}", callback_data=f"TR_{c}"))
        if len(row) == 2:
            keyboard.append(row); row = []
    if row: keyboard.append(row)
    keyboard.append([
        InlineKeyboardButton("🗑 Hammasini tozala", callback_data="TR_CLEAR"),
        InlineKeyboardButton("✅ Tayyor",            callback_data="TR_DONE"),
    ])
    sel = ", ".join(u["trailers"]) if u["trailers"] else "hech biri"
    await q.edit_message_text(
        f"🚛 *Trailer turini tanlang* (hozir: {sel})\nBir nechta tanlash mumkin:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
 
# ─── /states ─────────────────────────────────────────────────────────
async def states_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u   = get_user(uid)
    keyboard = []
    row = []
    for st in US_STATES:
        chk = "✅" if st in u["states"] else "  "
        row.append(InlineKeyboardButton(f"{chk}{st}", callback_data=f"ST_{st}"))
        if len(row) == 5:
            keyboard.append(row); row = []
    if row: keyboard.append(row)
    keyboard.append([
        InlineKeyboardButton("🗑 Tozala",  callback_data="ST_CLEAR"),
        InlineKeyboardButton("✅ Tayyor",  callback_data="ST_DONE"),
    ])
    sel = ", ".join(u["states"]) if u["states"] else "hech biri"
    await update.message.reply_text(
        f"🗺 *Shtatlarni tanlang* (hozir: {sel})\nBir nechta tanlash mumkin:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
 
async def state_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q   = update.callback_query; await q.answer()
    uid = q.from_user.id
    u   = get_user(uid)
    code = q.data.replace("ST_","")
    if code == "CLEAR":
        u["states"] = []
    elif code == "DONE":
        sel = ", ".join(u["states"]) if u["states"] else "barchasi"
        await q.edit_message_text(
            f"✅ Shtatlar tanlandi: *{sel}*\nEndi /loads bilan yuklarni ko'ring!",
            parse_mode="Markdown"
        )
        return
    else:
        if code in u["states"]: u["states"].remove(code)
        else: u["states"].append(code)
 
    keyboard = []
    row = []
    for st in US_STATES:
        chk = "✅" if st in u["states"] else "  "
        row.append(InlineKeyboardButton(f"{chk}{st}", callback_data=f"ST_{st}"))
        if len(row) == 5:
            keyboard.append(row); row = []
    if row: keyboard.append(row)
    keyboard.append([
        InlineKeyboardButton("🗑 Tozala",  callback_data="ST_CLEAR"),
        InlineKeyboardButton("✅ Tayyor",  callback_data="ST_DONE"),
    ])
    sel = ", ".join(u["states"]) if u["states"] else "hech biri"
    await q.edit_message_text(
        f"🗺 *Shtatlarni tanlang* (hozir: {sel})\nBir nechta tanlash mumkin:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
 
# ─── /loads ──────────────────────────────────────────────────────────
async def loads_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u   = get_user(uid)
    states   = u["states"]   if u["states"]   else random.sample(US_STATES, 5)
    trailers = u["trailers"] if u["trailers"] else list(TRAILER_TYPES.keys())
 
    await update.message.reply_text("⏳ Yuklar qidirilmoqda...")
    loads = generate_demo_loads(states, trailers, count=12)
 
    hot_loads  = [l for l in loads if is_hot(l) and not is_scam(l)[0]]
    scam_loads = [l for l in loads if is_scam(l)[0]]
    good_loads = [l for l in loads if not is_hot(l) and not is_scam(l)[0]]
 
    # Update stats
    u["stats"]["loads_viewed"] += len(loads)
    u["stats"]["hot_found"]    += len(hot_loads)
    u["stats"]["scams_blocked"]+= len(scam_loads)
    u["history"].extend(loads[-5:])   # keep last 5
 
    # Save to global history
    load_history.extend(loads)
    if len(load_history) > 500: load_history[:] = load_history[-500:]
 
    msg = f"📦 *Yuklar topildi:* {len(loads)} ta\n🔥 HOT: {len(hot_loads)} | 🚫 Scam: {len(scam_loads)}\n\n"
 
    if scam_loads:
        msg += "━━━ 🚫 SCAM/FAKE YUKLAR ━━━\n"
        for i, l in enumerate(scam_loads, 1):
            msg += fmt_load(l, i)
        msg += "\n"
 
    if hot_loads:
        msg += "━━━ 🔥 HOT YUKLAR ━━━\n"
        for i, l in enumerate(hot_loads, 1):
            msg += fmt_load(l, i)
        msg += "\n"
 
    if good_loads:
        msg += "━━━ 📦 ODDIY YUKLAR ━━━\n"
        for i, l in enumerate(good_loads[:5], 1):
            msg += fmt_load(l, i)
 
    # Split long messages
    chunks = [msg[i:i+4000] for i in range(0, len(msg), 4000)]
    for chunk in chunks:
        await update.message.reply_text(chunk, parse_mode="Markdown")
 
    # Post to channel if configured
    if CHANNEL_ID and hot_loads:
        try:
            ch_msg = f"🔥 *HOT YUKLAR — {datetime.now().strftime('%H:%M')}*\n\n"
            for i, l in enumerate(hot_loads[:3], 1):
                ch_msg += fmt_load(l, i)
            await ctx.bot.send_message(CHANNEL_ID, ch_msg, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Channel post failed: {e}")
 
# ─── /monitor ────────────────────────────────────────────────────────
async def monitor_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u   = get_user(uid)
    args = ctx.args
    if args and args[0].lower() == "on":
        u["monitor"] = True
        ctx.job_queue.run_repeating(
            monitor_job, interval=300, first=10,
            chat_id=update.effective_chat.id,
            name=str(uid), data=uid
        )
        await update.message.reply_text("✅ Monitoring yoqildi! Har 5 daqiqada yangi HOT yuklar keladi.")
    elif args and args[0].lower() == "off":
        u["monitor"] = False
        jobs = ctx.job_queue.get_jobs_by_name(str(uid))
        for job in jobs: job.schedule_removal()
        await update.message.reply_text("⏹ Monitoring to'xtatildi.")
    else:
        status = "✅ Yoqiq" if u["monitor"] else "⏹ O'chiq"
        await update.message.reply_text(
            f"🔴 Monitor holati: {status}\n/monitor on — yoqish\n/monitor off — o'chirish"
        )
 
async def monitor_job(ctx: ContextTypes.DEFAULT_TYPE):
    uid     = ctx.job.data
    chat_id = ctx.job.chat_id
    u       = get_user(uid)
    if not u["monitor"]: return
    states   = u["states"]   if u["states"]   else random.sample(US_STATES, 3)
    trailers = u["trailers"] if u["trailers"] else list(TRAILER_TYPES.keys())
    loads    = generate_demo_loads(states, trailers, count=8)
    hot      = [l for l in loads if is_hot(l) and not is_scam(l)[0]]
    if hot:
        msg = f"🔔 *YANGI HOT YUKLAR* — {datetime.now().strftime('%H:%M')}\n\n"
        for i, l in enumerate(hot[:3], 1):
            msg += fmt_load(l, i)
        await ctx.bot.send_message(chat_id, msg, parse_mode="Markdown")
 
# ─── /rates — Narx tahlili ───────────────────────────────────────────
async def rates_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u   = get_user(uid)
    trailers = u["trailers"] if u["trailers"] else list(TRAILER_TYPES.keys())
 
    # Simulate rate trends
    msg = "📊 *Narx Tahlili (Rate Trends)*\n\n"
    for tr in trailers[:4]:
        label = TRAILER_TYPES[tr]
        avg  = round(random.uniform(2.0, 3.8), 2)
        hi   = round(avg + random.uniform(0.3, 0.8), 2)
        lo   = round(avg - random.uniform(0.2, 0.6), 2)
        trend= random.choice(["📈 +3.2%", "📉 -1.5%", "📈 +5.1%", "➡️ 0.0%"])
        msg += (
            f"🚛 *{label}*\n"
            f"   Avg: ${avg}/mil  |  High: ${hi}  |  Low: ${lo}\n"
            f"   Trend (7 kun): {trend}\n\n"
        )
 
    msg += (
        "📌 *Eng yuqori to'lovli yo'nalishlar:*\n"
        "   🥇 CA → TX: avg $3.80/mil\n"
        "   🥈 FL → NY: avg $3.60/mil\n"
        "   🥉 WA → CA: avg $3.40/mil\n\n"
        "⚠️ _Bu ko'rsatkichlar demo ma'lumotlarga asoslangan._\n"
        "_Haqiqiy narxlar uchun DAT yoki Truckstop API kerak._"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")
 
# ─── /stats ──────────────────────────────────────────────────────────
async def stats_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u   = get_user(uid)
    s   = u["stats"]
    states_sel  = ", ".join(u["states"])   if u["states"]   else "Barcha"
    trailers_sel= ", ".join(u["trailers"]) if u["trailers"] else "Barcha"
    msg = (
        f"📊 *Sizning statistikangiz*\n\n"
        f"📍 Shtatlar: {states_sel}\n"
        f"🚛 Trailerlar: {trailers_sel}\n\n"
        f"📦 Ko'rilgan yuklar: {s['loads_viewed']}\n"
        f"🔥 HOT yuklar: {s['hot_found']}\n"
        f"🚫 Bloklangan scamlar: {s['scams_blocked']}\n"
        f"🔴 Monitoring: {'Yoqiq ✅' if u['monitor'] else 'O\'chiq ⏹'}\n\n"
        f"📅 Sessiya: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")
 
# ─── /help ───────────────────────────────────────────────────────────
async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🚛 *Freight Monitor Bot — Buyruqlar*\n\n"
        "/start       — Botni boshlash\n"
        "/trailer     — Trailer turini tanlash (Van, Flatbed...)\n"
        "/states      — Shtatlarni tanlash\n"
        "/loads       — Yuklarni ko'rish\n"
        "/monitor on  — Avtomatik monitoring (5 min)\n"
        "/monitor off — Monitoringni to'xtatish\n"
        "/rates       — Narx tahlili & trendlar\n"
        "/stats       — Sizning statistikangiz\n"
        "/help        — Shu yordam xabari\n\n"
        "🔥 HOT yuk: $3.00+/mil yoki 1000+ mil\n"
        "🚫 Scam: MC yo'q, avans to'lov, past reyting\n"
        "🟢 Broker AI Score: 70+ = ishonchli\n\n"
        "⚠️ _Bot demo mode da ishlayapti._\n"
        "_DAT API bilan haqiqiy yuklar ko'rinadi._"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")
 
# ─── Main ─────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TOKEN).build()
 
    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("trailer", trailer_cmd))
    app.add_handler(CommandHandler("states",  states_cmd))
    app.add_handler(CommandHandler("loads",   loads_cmd))
    app.add_handler(CommandHandler("monitor", monitor_cmd))
    app.add_handler(CommandHandler("rates",   rates_cmd))
    app.add_handler(CommandHandler("stats",   stats_cmd))
    app.add_handler(CommandHandler("help",    help_cmd))
 
    app.add_handler(CallbackQueryHandler(trailer_cb, pattern="^TR_"))
    app.add_handler(CallbackQueryHandler(state_cb,   pattern="^ST_"))
 
    logger.info("Bot started ✅")
    app.run_polling(drop_pending_updates=True)
 
if __name__ == "__main__":
    main()

