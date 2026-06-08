import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Tokens (nom nom nom, tasty 🤤😝)
TOKEN = os.getenv("DISCORD_TOKEN")
DEBUG_MODE = os.getenv("LOGGING_DEBUG_MODE")
if not DEBUG_MODE is None and DEBUG_MODE.lower() == "true":
    LOGGING_DEBUG_MODE = True
else:
    LOGGING_DEBUG_MODE = False
if not TOKEN:
    raise SystemExit("Set DISCORD_TOKEN in .env")
gemini_api_key = os.getenv("GEMINI_API_KEY", None)

# Base directory
BASE_DIR = Path(__file__).resolve().parent

# Database paths
prompt = str(BASE_DIR / "databases" / "prompt.txt")
with open(prompt, "r", encoding="utf-8") as f:
    system_prompt = f.read().strip()

