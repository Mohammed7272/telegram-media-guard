import os
from pathlib import Path
from dotenv import load_dotenv
from cryptography.fernet import Fernet

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"

# Load .env file
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)
else:
    load_dotenv()

API_ID_RAW = os.getenv("API_ID")
API_ID = int(API_ID_RAW) if API_ID_RAW and API_ID_RAW.isdigit() else 0
API_HASH = os.getenv("API_HASH", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DATABASE_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "guard.db"))

raw_key = os.getenv("ENCRYPTION_KEY", "").strip()
if not raw_key:
    # Auto-generate key if not set
    generated = Fernet.generate_key().decode()
    ENCRYPTION_KEY = generated.encode()
    print(f"[!] No ENCRYPTION_KEY found. Generated new key for this session: {generated}")
else:
    ENCRYPTION_KEY = raw_key.encode()

def validate_config() -> bool:
    """Validates that necessary Telegram credentials exist."""
    missing = []
    if not API_ID:
        missing.append("API_ID")
    if not API_HASH:
        missing.append("API_HASH")
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    
    if missing:
        print(f"[!] Error: Missing configuration values in .env: {', '.join(missing)}")
        print("    Please copy .env.example to .env and fill in your credentials.")
        return False
    return True
