import asyncio
import logging
import os
from telethon import TelegramClient, events

# O'zgaruvchilarni Railway Environment Variables'dan oladi
API_ID = int(os.environ.get("API_ID", "35076613"))
API_HASH = os.environ.get("API_HASH", "5f51e95e90785a08d396d13c1e6dc5f1")
# Userbot uchun session nomi
SESSION_NAME = "freight_session" 
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

async def main():
    # Bu yerda shaxsiy akkaunt bilan kiramiz
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    
    await client.start() # Bu yerda kod so'raydi (pastga qarang)
    logger.info("✅ Akkaunt muvaffaqiyatli bog'landi!")

    @client.on(events.NewMessage(chats=list(SOURCE_CHANNELS.keys())))
    async def handler(event):
        try:
            channel_name = SOURCE_CHANNELS.get(event.chat_id, "Unknown")
            text = event.message.message or ""
            
            if text.strip():
                formatted = f"🚛 NEW LOAD\n\n📍 Broker: {channel_name}\n📝 Info:\n{text}"
                await client.send_message(TARGET_CHANNEL, formatted)
                logger.info(f"✅ Yuborildi: {channel_name}")
        except Exception as e:
            logger.error(f"Xato: {e}")

    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
