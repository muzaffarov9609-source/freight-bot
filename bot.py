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

# Sessiya fayli yo'lini aniqlash
SESSION_NAME = "new_freight_session"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_PATH = os.path.join(BASE_DIR, f"{SESSION_NAME}.session")

# 2. MONITOR QILINADIGAN KANALLAR
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

# 3. LOGGING (Xatolarni kuzatish uchun)
logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Duplikat xabarlarni filtrlash uchun
seen_messages = set()

async def main():
    logger.info("🚀 FREIGHT MONITOR STARTING...")
    
    # Sessiya fayli borligini tekshirish
    if not os.path.exists(SESSION_PATH):
        logger.error(f"❌ XATO: {SESSION_PATH} topilmadi!")
        logger.info(f"Papkadagi fayllar: {os.listdir(BASE_DIR)}")
        return

    # Kliyentni ishga tushiramiz
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    
    try:
        await client.start()
        logger.info("✅ Akkaunt muvaffaqiyatli bog'landi!")
        
        me = await client.get_me()
        logger.info(f"✅ Monitoring James (@{me.username}) orqali ishlayapti.")

        # 4. XABARLARNI TUTISH HANDLERI
        @client.on(events.NewMessage(chats=list(SOURCE_CHANNELS.keys())))
        async def handler(event):
            try:
                # Kanal ma'lumotlarini olish
                channel_id = event.chat_id
                channel_name = SOURCE_CHANNELS.get(channel_id, "Unknown Channel")
                
                # Matnni xavfsiz usulda olish
                text = event.raw_text
                if not text or len(text.strip()) < 5: # Bo'sh yoki juda qisqa xabarlarni skip qilish
                    return

                # Duplikatlarni tekshirish (Kanal ID va Xabar ID orqali)
                msg_key = f"{channel_id}:{event.id}"
                if msg_key in seen_messages:
                    return
                seen_messages.add(msg_key)

                # Ro'yxatni juda kattalashib ketishidan saqlash
                if len(seen_messages) > 1000:
                    seen_messages.clear()

                # Vaqtni formatlash
                now = datetime.now().strftime("%H:%M")

                # Xabarni chiroyli ko'rinishga keltirish
                formatted_text = (
                    f"🚛 **NEW LOAD ALERT**\n\n"
                    f"📍 **Broker:** {channel_name}\n"
                    f"📝 **Details:**\n{text}\n\n"
                    f"⏰ **Time:** {now}"
                )

                # O'z kanalingizga yuborish
                await client.send_message(
                    TARGET_CHANNEL, 
                    formatted_text, 
                    link_preview=False
                )
                logger.info(f"✅ YUBORILDI: [{channel_name}]")

            except Exception as e:
                # Xato chiqsa bot to'xtab qolmasligi uchun faqat log qilamiz
                logger.error(f"❌ Handler Error: {e}")

        logger.info("🎯 Bot tayyor! Kanallarni kuzatish boshlandi.")
        await client.run_until_disconnected()

    except Exception as e:
        logger.error(f"❌ Fatal Error: {e}")
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 Bot to'xtatildi.")
