import os
from dotenv import load_dotenv

load_dotenv()


def _split_ids(raw: str) -> set[str]:
    return {x.strip() for x in raw.split(",") if x.strip()}


TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_WEBHOOK_SECRET = os.environ["TELEGRAM_WEBHOOK_SECRET"]
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")

SHOP_NAME = os.environ.get("SHOP_NAME", "My Super Market")


