import asyncio
import logging
import os
import base64
from telethon import TelegramClient, events
from telethon.sessions import MemorySession
from telethon.crypto import AuthKey

API_ID = int(os.environ.get("API_ID", "35076613"))
API_HASH = os.environ.get("API_HASH", "5f51e95e90785a08d396d13c1e6dc5f1")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "7950311441:AAHI4X3lnVYIzDgXO9SlUhdSpXmBDpHurJU")
TARGET_CHANNEL = int(os.environ.get("TARGET_CHANNEL", "-1001803815649758"))

# Session ma'lumotlari (freight_session.session dan olindi)
SESSION_DC_ID = 2
SESSION_SERVER = "149.154.167.51"
SESSION_PORT = 443
SESSION_AUTH_KEY = base64.b64decode("N21Grz7xB11Aub3Km11eZoFGQJHGeaXm83HqdZ/OdgOwgEiaJaNJfu8bcKyNd/MO8Ra7aTvTsTP5vQW6USbdrikwBcAi3nox/WslTiF6Zpbzl/X0q1K/oQFLlWqIxSXzDqOO4G6rJXaEbFCvg24QJeMvriNB0Lhg9iMb6uVoZTHAiwTXqDdVndHsGMf65tbi6z9KsPgxuCR6n+UxZRI/Ua4FQjRE3T+WoSIqhm49u5u9uBoeo+SZtDwGgaxMLBJTViq9IRDlc0n0tSuAk64RUqz05BZtLfnNIsA7JvTef/wvECRaa3t33JufODJFArKHl7O57/LTHPkVQ8xYiCohPw==")

SOURCE_CHANNELS = {
    -1002448589077: "Street brokers IDS/S3",
    -1001480955628: "RXO/CAYOTE/XPO",
    -1001701195430: "Forward Air",
    -1001200307642: "UTXL",
    -1001918460833: "Landstar",
    -1001695069850: "ITS",
    -1001809209156: "Lipsey(USPS)",
    -1001830666765: "ITS/A1",
    -1001233677769: "OneBrokeredge",
    -1002045367640: "Forward Air (Only PO)",
    -1002119835661: "Syfan",
    -1001453519184: "OTC logistics PO",
    -1002386910861: "GH Logistics",
    -1002560784901: "Ben_USPS",
    -1002271799783: "ITS PO only",
    -1001292793466: "PO/VAN/Refer",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

seen_messages = set()

def is_duplicate(channel_id, message_id):
    key = f"{channel_id}:{message_id}"
    if key in seen_messages:
        return True
    seen_messages.add(key)
    if len(seen_messages) > 10000:
        for item in list(seen_messages)[:5000]:
            seen_messages.discard(item)
    return False

async def main():
    logger.info("Bot ishga tushmoqda...")

    # Memory session - fayl shart emas
    session = MemorySession()
    session.set_dc(SESSION_DC_ID, SESSION_SERVER, SESSION_PORT)
    session.auth_key = AuthKey(data=SESSION_AUTH_KEY)

    client = TelegramClient(session, API_ID, API_HASH)
    await client.connect()
    logger.info("✅ Telegram-ga ulandi!")

    bot = TelegramClient("bot_session", API_ID, API_HASH)
    await bot.start(bot_token=BOT_TOKEN)
    logger.info("✅ Bot ulandi!")

    source_ids = list(SOURCE_CHANNELS.keys())
    logger.info(f"📡 {len(source_ids)} ta kanal kuzatilmoqda...")

    @client.on(events.NewMessage(chats=source_ids))
    async def handler(event):
        try:
            channel_id = event.chat_id
            message_id = event.message.id
            channel_name = SOURCE_CHANNELS.get(channel_id, "Noma'lum")

            if is_duplicate(channel_id, message_id):
                return

            text = event.message.message or ""
            if not text.strip():
                return

            forwarded_text = f"📦 [{channel_name}]\n\n{text}"
            await bot.send_message(TARGET_CHANNEL, forwarded_text, link_preview=False)
            logger.info(f"✅ Yuborildi: [{channel_name}] - msg_id:{message_id}")

        except Exception as e:
            logger.error(f"❌ Xato: {e}")
# Debug: qaysi kanallarga ulanganini tekshirish
    async for dialog in client.iter_dialogs():
        if dialog.id in source_ids:
            logger.info(f"✅ Kanal topildi: {dialog.name} ({dialog.id})")
    

    logger.info("🚀 Bot tayyor! Kanallarni kuzatyapman...")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
