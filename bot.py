import asyncio
import logging
import os
from datetime import datetime
from telethon import TelegramClient, events

# 1. KONFIGURATSIYA
API_ID = int(os.environ.get("API_ID", "35076613"))
API_HASH = os.environ.get("API_HASH", "5f51e95e90785a08d396d13c1e6dc5f1")
TARGET_CHANNEL = int(os.environ.get("TARGET_CHANNEL", "-1001803815649758"))

# Sessiya fayli yo'li
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

    if not os.path.exists(SESSION_PATH):
        logger.error(f"❌ {SESSION_PATH} topilmadi!")
        return

    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    
    try:
        await client.start()
        logger.info("✅ Akkaunt muvaffaqiyatli bog'landi!")
        
        @client.on(events.NewMessage(chats=list(SOURCE_CHANNELS.keys())))
        async def handler(event):
            # Xatolik chiqsa ham botni to'xtatmaslik uchun try-except
            try:
                # Faqat matnli xabarlarni olamiz
                msg_text = event.message.message
                if not msg_text:
                    return

                ch_id = event.chat_id
                ch_name = SOURCE_CHANNELS.get(ch_id, "Unknown")
                
                # Oddiy string birlashtirish (indekssiz)
                res = f"🚛 **NEW LOAD**\n\n"
                res += f"📍 **Broker:** {ch_name}\n"
                res += f"📝 **Info:**\n{msg_text}\n\n"
                res += f"⏰ {datetime.now().strftime('%H:%M')}"
                
                await client.send_message(TARGET_CHANNEL, res, link_preview=False)
                logger.info(f"✅ YUBORILDI: {ch_name}")

            except Exception as e:
                logger.error(f"⚠️ Xabar yuborishda xato: {e}")

        logger.info("🎯 Bot tayyor! Kuzatuv boshlandi.")
        await client.run_until_disconnected()

    except Exception as e:
        logger.error(f"❌ Fatal Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
