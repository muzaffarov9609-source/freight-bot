import asyncio
import logging
import os
import traceback
from datetime import datetime
from telethon import TelegramClient, events

# 1. KONFIGURATSIYA (Railway Environment Variables'dan oladi)
API_ID = int(os.environ.get("API_ID", "35076613"))
API_HASH = os.environ.get("API_HASH", "5f51e95e90785a08d396d13c1e6dc5f1")
TARGET_CHANNEL = int(os.environ.get("TARGET_CHANNEL", "-1001803815649758"))
SESSION_NAME = "freight_session" # .session fayli nomi

# 2. MONITOR QILINADIGAN KANALLAR RO'YXATI
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

# 3. LOGGING (Xatolarni ko'rish uchun)
logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Duplikatlarni oldini olish uchun
seen_messages = set()

def is_duplicate(channel_id, message_id):
    key = f"{channel_id}:{message_id}"
    if key in seen_messages:
        return True
    seen_messages.add(key)
    if len(seen_messages) > 5000:
        seen_messages.clear()
    return False

def format_message(channel_name, text):
    now = datetime.now().strftime("%d %b %Y, %H:%M")
    return (
        f"🚛 **NEW LOAD**\n\n"
        f"📍 **Broker:** {channel_name}\n"
        f"📝 **Info:**\n{text}\n\n"
        f"⏰ **Time:** {now}"
    )

async def main():
    logger.info("🚀 FREIGHT MONITOR ISHGA TUSHMOQDA...")
    
    # 4. KLIYENTNI ISHGA TUSHIRISH
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    
    try:
        await client.start()
        logger.info("✅ Akkaunt muvaffaqiyatli bog'landi!")
        
        me = await client.get_me()
        logger.info(f"✅ Foydalanuvchi: {me.first_name} (@{me.username})")
        
    except Exception as e:
        logger.error(f"❌ Ulana olmadi. Sababi: {e}")
        return

    # 5. XABARLARNI TUTIB OLISH HANDLERI
    @client.on(events.NewMessage(chats=list(SOURCE_CHANNELS.keys())))
    async def handler(event):
        try:
            channel_id = event.chat_id
            channel_name = SOURCE_CHANNELS.get(channel_id, "Unknown Channel")
            
            # Debug: Logda har bir kelgan xabarni ko'rish
            logger.info(f"📩 Yangi xabar keldi: [{channel_name}] (ID: {channel_id})")

            if is_duplicate(channel_id, event.id):
                return

            text = event.message.message or ""
            if not text.strip():
                return

            # Xabarni formatlash va yuborish
            formatted_text = format_message(channel_name, text)
            
            await client.send_message(
                TARGET_CHANNEL, 
                formatted_text, 
                link_preview=False
            )
            logger.info(f"✅ YUBORILDI: {channel_name}")

        except Exception as e:
            logger.error(f"❌ Handlerda xatolik: {e}")

    logger.info(f"📡 {len(SOURCE_CHANNELS)} ta kanal kuzatilyapti...")
    await client.run_until_disconnected()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
