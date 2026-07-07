import os
import logging
from dotenv import load_dotenv
from cryptography.fernet import Fernet

load_dotenv("config.env")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "")
if not ENCRYPTION_KEY:
    ENCRYPTION_KEY = Fernet.generate_key().decode()
    logger.warning("No ENCRYPTION_KEY set. Generated ephemeral key — existing keys won't survive restart.")
_fernet = Fernet(ENCRYPTION_KEY.encode() if isinstance(ENCRYPTION_KEY, str) else ENCRYPTION_KEY)

TELEGRAM_MSG_LIMIT = 4000
OR_PAGE_SIZE = 8
OR_CACHE_TTL = 3600

def get_fernet() -> Fernet:
    return _fernet
