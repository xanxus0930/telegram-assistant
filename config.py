import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

PROVIDER_ORDER = ["gemini", "nvidia", "openrouter"]

DEFAULT_MODELS = {
    "gemini": "gemini-2.0-flash",
    "nvidia": "meta/llama-3.3-70b-instruct",
    "openrouter": "anthropic/claude-3.5-haiku",
}

MAX_HISTORY = 40

DEFAULT_PERSONA = "你是一個聰明、友善的個人助理，使用繁體中文回答，可以幫助用戶完成各種任務。"

DB_PATH = os.getenv("DB_PATH", "bot.db")

TIMEZONE = "Asia/Taipei"
