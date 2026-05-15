import asyncio
import logging
import os
import traceback
from datetime import datetime
from telethon import TelegramClient, events

API_ID = int(os.environ.get("API_ID", "35076613"))
API_HASH = os.environ.get("API_HASH", "5f51e95e90785a08d396d13c1e6dc5f1")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "7950311441:AAHI4X3lnVYIzDgXO9SlUhdSpXmBDpHurJU")
TARGET_CHANNEL = int(os.environ.get("TARGET_CHANNEL", "-1001803815649758"))
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

def format_message(channel_name, text):
    now = datetime.now().strftime("%d %b %Y, %H:%M")
    return (
        f"🚛 NEW LOAD\n\n"
        f"📍 Broker: {channel_name}\n"
        f"📝 Info:\n{text}\n\n"
        f"⏰ Time: {now}"
    )

async def main():
    logger.info("Bot ishga tushmoqda...")

    client = TelegramClient("freight_session", API_ID, API_HASH)
    await client.start()
    logger.info("✅ Telegram-ga ulandi!")

    bot = TelegramClient("bot_session", API_ID, API_HASH)
    await bot.start(bot_token=BOT_TOKEN)
    logger.info("✅ Bot ulandi!")

    # Target channel entity oldindan olinadi
    try:
        target_entity = await bot.get_entity(TARGET_CHANNEL)
        logger.info(f"✅ Target kanal tayyor: {target_entity.title}")
    except Exception as e:
        logger.error(f"❌ Target kanalga ulanib bo'lmadi: {e}")
        return

    channel_entities = []
    async for dialog in client.iter_dialogs():
        if dialog.id in SOURCE_CHANNELS:
            channel_entities.append(dialog.entity)
            logger.info(f"✅ Kanal tayyor: {dialog.name}")

    if not channel_entities:
        logger.error("❌ Hech qanday manba kanal topilmadi!")
        return

    logger.info(f"📡 {len(channel_entities)} ta kanal kuzatilmoqda...")

    @client.on(events.NewMessage(chats=channel_entities))
    async def handler(event):
        try:
            channel_id = event.chat_id
            message_id = event.message.id
            channel_name = SOURCE_CHANNELS.get(channel_id, "Unknown")

            if is_duplicate(channel_id, message_id):
                return

            text = event.message.message or event.message.text or ""
            if not text.strip():
                logger.info(f"⏭️ Empty message skipped: [{channel_name}]")
                return

            formatted = format_message(channel_name, text)

            # ✅ bot orqali yuborish (client emas!)
            await bot.send_message(
                target_entity,
                formatted,
                link_preview=False
            )
            logger.info(f"✅ Sent: [{channel_name}] - msg_id:{message_id}")

        except Exception as e:
            logger.error(f"❌ Error: {e}")
            logger.error(traceback.format_exc())

    logger.info("🚀 Bot tayyor! Kanallarni kuzatyapman...")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
