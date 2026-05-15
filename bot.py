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
    logger.info("=" * 60)
    logger.info("🚀 BOT ISHGA TUSHMOQDA...")
    logger.info("=" * 60)

    bot = TelegramClient("bot_session", API_ID, API_HASH)
    
    try:
        await bot.start(bot_token=BOT_TOKEN)
        logger.info("✅ Bot Telegram-ga ulandi!")
    except Exception as e:
        logger.error(f"❌ Bot ulana olmadi: {e}")
        return

    try:
        channel_entities = []
        
        for channel_id in SOURCE_CHANNELS.keys():
            try:
                entity = await bot.get_entity(channel_id)
                channel_entities.append(entity)
                logger.info(f"✅ Kanal ulandi: {SOURCE_CHANNELS[channel_id]}")
            except Exception as e:
                logger.warning(f"⚠️ Kanal topilmadi ({channel_id}): {str(e)[:50]}")

        logger.info(f"📡 {len(channel_entities)} ta kanal kuzatilmoqda...")
        logger.info("=" * 60)

        @bot.on(events.NewMessage(chats=channel_entities))
        async def handler(event):
            try:
                channel_id = event.chat_id
                message_id = event.message.id
                channel_name = SOURCE_CHANNELS.get(channel_id, "Unknown")

                if is_duplicate(channel_id, message_id):
                    logger.info(f"🔄 Duplikat: [{channel_name}] (msg_id:{message_id})")
                    return

                text = event.message.message or event.message.text or ""

                if not text.strip():
                    logger.info(f"⏭️ Bo'sh xabar skip: [{channel_name}]")
                    return

                formatted = format_message(channel_name, text)

                try:
                    await bot.send_message(
                        TARGET_CHANNEL,
                        formatted,
                        link_preview=False
                    )
                    logger.info(f"✅ YUBORILDI: [{channel_name}] - msg_id:{message_id}")

                except Exception as send_err:
                    logger.error(f"❌ Send Error [{channel_name}]: {send_err}")

            except Exception as e:
                logger.error(f"❌ Handler Error: {e}")
                logger.error(traceback.format_exc())

        logger.info("🎯 Bot tayyor! Kanallarni kuzatyapman...\n")

        await bot.run_until_disconnected()

    except Exception as e:
        logger.error(f"❌ XATO: {e}")
        logger.error(traceback.format_exc())
    finally:
        await bot.disconnect()
        logger.info("✅ Bot to'xtatildi")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Bot to'xtatildi (CTRL+C)")
    except Exception as e:
        logger.error(f"❌ Fatal Error: {e}")
        logger.error(traceback.format_exc())
