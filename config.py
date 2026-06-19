import os
from pathlib import Path
from dotenv import load_dotenv
import time # for debouncing (double read)
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

load_dotenv()

# Tokens (nom nom nom, tasty 🤤😝)
TOKEN = os.getenv("DISCORD_TOKEN")
DEBUG_MODE = os.getenv("LOGGING_DEBUG_MODE")
PROXY_USERNAME = os.getenv("PROXY_USERNAME")
PROXY_PASSWORD = os.getenv("PROXY_PASSWORD")

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
_PROMPT_PATH = BASE_DIR / "prompts" / "prompt.txt"
system_prompt = "" # What we send to Gemma each call





class PromptWatcherHandler(FileSystemEventHandler):
    """Listens for operating system file events and triggers a reload."""
    def __init__(self):
        super().__init__()
        self.last_modified = 0

    def on_modified(self, event):
        global system_prompt
        
        # Ensure we are ONLY responding to edits on our specific prompt file
        if event.src_path == str(_PROMPT_PATH):
            current_time = time.time()
            # Safety Gate: Prevent duplicate double-fire OS triggers within 1 second
            if current_time - self.last_modified < 1.0:
                return
            self.last_modified = current_time

            print("[HOT-RELOAD] prompt.txt modification detected! Updating prompt...")
            try:
                # Read the file once into RAM, then immediately close it
                with open(_PROMPT_PATH, "r", encoding="utf-8") as f:
                    system_prompt = f.read().strip()
                print(f"[HOT-RELOAD] Successfully reloaded! New prompt length: {len(system_prompt):,} characters.")
            except Exception as e:
                print(f"[HOT-RELOAD ERROR] Failed to read prompt file: {e}")

def init_prompt_watcher():
    """Initializes the prompt in memory and boots the background thread listener."""
    global system_prompt
    
    # 1. Do the initial boot load so the bot has the prompt ready immediately
    if not _PROMPT_PATH.exists():
        raise FileNotFoundError(f"Critical Error: {_PROMPT_PATH} does not exist!")
        
    with open(_PROMPT_PATH, "r", encoding="utf-8") as f:
        system_prompt = f.read().strip()

    # 2. Setup the Watchdog observer to run silently on a separate background thread
    handler = PromptWatcherHandler()
    observer = Observer()
    
    # Watchdog monitors directories, so we point it to the 'prompts' folder
    observer.schedule(handler, path=str(_PROMPT_PATH.parent), recursive=False)
    observer.start()
    print("[INIT] Operating system file-watcher started successfully for prompt.txt")

### EOF: /twilight-ai/config.py ###