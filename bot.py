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

SESSION_NAME = "super_stable_session"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_PATH = os.path.join(BASE_DIR, f"{SESSION_NAME}.session")

# 2. MONITOR KANALLARI
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

# 3. FILTRLAR (Yumshoq va faqat yuklar uchun)
KEYWORDS = ["PO", "VNL", "VAN", "LOAD", "READY", "OFFER", "TEAM", "SOLO", "RPM", "MILES", "TRIP", "PICK", "DROP"]
BLACKLIST = ["join channel", "subscribe", "obuna bo'ling", "reklama sotiladi"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

async def main():
    logger.info("🚀 USERNAME FREIGHT MONITOR STARTING...")
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH, connection_retries=None)
    
    try:
        await client.start()
        logger.info("✅ Akkaunt bog'landi!")
        
        @client.on(events.NewMessage())
        async def handler(event):
            try:
                if event.chat_id not in SOURCE_CHANNELS:
                    return

                # Xabarni markdown entitiylari (bosiladigan havolalar, ko'k usernames) bilan birga olamiz
                msg_text = event.message.message
                if not msg_text:
                    return

                text_lower = msg_text.lower()

                # 1. REKLAMA FILTRI
                if any(bad in text_lower for bad in BLACKLIST):
                    return

                # 2. YUK VA SHTAT TEKSHIRUVI
                has_usa_state = bool(re.search(r'\b[A-Z]{2}\b', msg_text))
                has_keyword = any(good in msg_text.upper() for good in KEYWORDS)
                # Agar broker shunchaki @username qoldirgan bo'lsa ham yuk deb hisoblasin
                has_at_username = "@" in msg_text 

                if has_keyword or has_usa_state or has_at_username:
                    ch_name = SOURCE_CHANNELS.get(event.chat_id, "Unknown")
                    
                    # Matn ichidagi barcha @usernamelarni qidirib topish
                    usernames = re.findall(r'@\w+', msg_text)
                    broker_contacts = ""
                    
                    if usernames:
                        # Noyob (duplicate bo'lmagan) usernamelarni saralab olamiz
                        unique_users = list(set(usernames))
                        broker_contacts = "\n\n👤 **Brokers to contact:** " + ", ".join(unique_users)

                    # CHUQQUR FORMATLANGAN SHABLON
                    now = datetime.now().strftime("%H:%M")
                    res = (
                        f"🚚 **{ch_name}**\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"{msg_text}"
                        f"{broker_contacts}\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"🕒 {now} | #FREIGHT"
                    )
                    
                    # Xabarni o'z kanalingizga yuborish
                    await client.send_message(TARGET_CHANNEL, res, link_preview=False)
                    logger.info(f"✅ YUBORILDI: {ch_name}")

            except Exception:
                pass

        await client.run_until_disconnected()
    except Exception as e:
        logger.error(f"❌ Fatal Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
