import asyncio
import logging
import os
from datetime import datetime
from telethon import TelegramClient, events

# 1. SOZLAMALAR
API_ID = int(os.environ.get("API_ID", "35076613"))
API_HASH = os.environ.get("API_HASH", "5f51e95e90785a08d396d13c1e6dc5f1")
TARGET_CHANNEL = int(os.environ.get("TARGET_CHANNEL", "-1001803815649758"))

SESSION_NAME = "new_freight_session"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_PATH = os.path.join(BASE_DIR, f"{SESSION_NAME}.session")

# 2. FILTRLAR
# Yukni anglatuvchi kalit so'zlar (faqat shu so'zlar bo'lsa yuboradi)
KEYWORDS = ["GA", "TX", "CA", "FL", "NY", "IL", "PO", "VNL", "DRY", "VAN", "LOAD", "READY", "OFFER", "TO:", "->"]
# Reklama so'zlari (shu so'zlar bo'lsa yubormaydi)
BLACKLIST = ["http", "t.me/", "join", "subscribe", "obuna", "reklama", "promo", "discount"]

SOURCE_CHANNELS = {
    -1002448589077: "Street brokers", -1001480955628: "RXO/CAYOTE",
    -1001701195430: "Forward Air", -1001200307642: "UTXL",
    -1001918460833: "Landstar", -1001695069850: "ITS",
    -1001809209156: "Lipsey", -1001830666765: "ITS/A1",
    -1001233677769: "OneBrokeredge", -1002045367640: "Forward PO",
    -1002119835661: "Syfan", -1001453519184: "OTC PO",
    -1002386910861: "GH Logistics", -1002560784901: "Ben_USPS",
    -1002271799783: "ITS PO only", -1001292793466: "PO/VAN/Refer"
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

async def main():
    logger.info("🚀 AQLLI FILTRLANGAN MONITOR STARTING...")
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    
    try:
        await client.start()
        logger.info("✅ Akkaunt bog'landi!")
        
        @client.on(events.NewMessage(chats=list(SOURCE_CHANNELS.keys())))
        async def handler(event):
            try:
                msg_text = event.message.message
                if not msg_text: return
                
                text_upper = msg_text.upper()

                # REKLAMA FILTRI: Agar xabarda reklama bo'lsa to'xtatamiz
                if any(word in msg_text.lower() for word in BLACKLIST):
                    logger.info("🚫 Reklama aniqlandi, o'chirildi.")
                    return

                # YUK FILTRI: Faqat yuk so'zlari bor xabarlarni olamiz
                if any(word in text_upper for word in KEYWORDS):
                    ch_name = SOURCE_CHANNELS.get(event.chat_id, "Unknown")
                    
                    # SIZ SO'RAGAN SHABLON (Tez va tushunarli)
                    res = (
                        f"🚚 **{ch_name}**\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"{msg_text}\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"🕒 {datetime.now().strftime('%H:%M')} | #FREIGHT"
                    )
                    
                    await client.send_message(TARGET_CHANNEL, res, link_preview=False)
                    logger.info(f"✅ YUBORILDI: {ch_name}")
                else:
                    logger.info("⏭️ Yukka aloqador emas, tashlab ketildi.")

            except Exception as e:
                logger.error(f"⚠️ Error: {e}")

        await client.run_until_disconnected()
    except Exception as e:
        logger.error(f"❌ Fatal Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
