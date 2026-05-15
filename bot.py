import asyncio
import logging
import os
from datetime import datetime
from telethon import TelegramClient, events

# 1. KONFIGURATSIYA
API_ID = int(os.environ.get("API_ID", "35076613"))
API_HASH = os.environ.get("API_HASH", "5f51e95e90785a08d396d13c1e6dc5f1")
TARGET_CHANNEL = int(os.environ.get("TARGET_CHANNEL", "-1001803815649758"))

# Sessiya fayli nomini va to'liq yo'lini aniqlaymiz
SESSION_NAME = "new_freight_session"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_PATH = os.path.join(BASE_DIR, f"{SESSION_NAME}.session")

# 2. KANALLAR RO'YXATI
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

async def main():
    logger.info("🚀 FREIGHT MONITOR STARTING...")
    logger.info(f"Checking for session file at: {SESSION_PATH}")

    # Fayl borligini tekshiramiz
    if not os.path.exists(SESSION_PATH):
        logger.error(f"❌ XATO: {SESSION_NAME}.session topilmadi!")
        logger.info(f"Papkadagi fayllar: {os.listdir(BASE_DIR)}")
        return

    # Kliyentni yaratishda to'liq yo'lni beramiz
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    
    try:
        await client.start()
        logger.info("✅ Akkaunt muvaffaqiyatli bog'landi!")
        
        @client.on(events.NewMessage(chats=list(SOURCE_CHANNELS.keys())))
        async def handler(event):
            try:
                channel_name = SOURCE_CHANNELS.get(event.chat_id, "Unknown")
                text = event.raw_text
                if not text: return

                now = datetime.now().strftime("%H:%M")
                formatted = f"🚛 **NEW LOAD**\n\n📍 **Broker:** {channel_name}\n📝 **Info:**\n{text}\n\n⏰ {now}"
                
                await client.send_message(TARGET_CHANNEL, formatted, link_preview=False)
                logger.info(f"✅ YUBORILDI: {channel_name}")
            except Exception as e:
                logger.error(f"Error: {e}")

        logger.info("🎯 Bot tayyor!")
        await client.run_until_disconnected()

    except Exception as e:
        logger.error(f"❌ Xato: {e}")

if __name__ == "__main__":
    asyncio.run(main())
