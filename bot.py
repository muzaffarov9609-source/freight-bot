import asyncio
import logging
import os
import re
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
KEYWORDS = ["GA", "TX", "CA", "FL", "NY", "IL", "PO", "VNL", "DRY", "VAN", "LOAD", "READY", "OFFER", "TO:", "->", "TEAM"]
BLACKLIST = ["http", "join", "subscribe", "obuna", "reklama", "promo", "discount"]

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
    logger.info("🚀 STABLE MONITOR STARTING...")
    # connection_retries - ulanish uzilsa qayta bog'lanish uchun
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH, connection_retries=None, retry_delay=5)
    
    try:
        await client.start()
        logger.info("✅ Akkaunt bog'landi!")
        
        @client.on(events.NewMessage(chats=list(SOURCE_CHANNELS.keys())))
        async def handler(event):
            try:
                msg_text = event.message.message
                if not msg_text: return
                
                # REKLAMA FILTRI
                if any(word in msg_text.lower() for word in BLACKLIST):
                    return

                # YUK FILTRI
                if any(word in msg_text.upper() for word in KEYWORDS):
                    ch_name = SOURCE_CHANNELS.get(event.chat_id, "Unknown")
                    
                    # Username-ni topish
                    usernames = re.findall(r'@\w+', msg_text)
                    contact_info = ""
                    if usernames:
                        contact_info = f"\n\n👤 **Broker:** {usernames[0]}"

                    # SHABLON
                    res = (
                        f"🚚 **{ch_name}**\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"{msg_text}"
                        f"{contact_info}\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"🕒 {datetime.now().strftime('%H:%M')} | #FREIGHT"
                    )
                    
                    await client.send_message(TARGET_CHANNEL, res, link_preview=False)
                    logger.info(f"✅ YUBORILDI: {ch_name}")

            except Exception as e:
                logger.error(f"⚠️ Handler Error: {e}")

        # Bot o'chib qolmasligi uchun cheksiz kutish
        await client.run_until_disconnected()
        
    except Exception as e:
        logger.error(f"❌ Fatal Error: {e}")
    finally:
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
