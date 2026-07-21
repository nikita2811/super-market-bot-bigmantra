import logging
from datetime import date, timedelta

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db import SessionLocal
from app.model import ChatSession
from app.tools.analytics_document import generate_report_pptx

logger = logging.getLogger("super-market-bot.scheduler")


def _target_chat_ids() -> list[str]:
    """Every chat_id that has ever messaged the bot, per chat_sessions.
    Dedupes just in case, and skips any null/empty rows defensively."""
    db = SessionLocal()
    try:
        rows = db.query(ChatSession.chat_id).distinct().all()
        return [chat_id for (chat_id,) in rows if chat_id]
    finally:
        db.close()


async def send_weekly_analysis_deck():
    """The scheduled job. Builds a deck for the last 7 completed days
    (yesterday back 6 more days, so the week is fully closed out — no
    partial 'today' data skewing the trend) and pushes it to every
    configured/known chat_id via Telegram sendDocument."""

    from app.main import send_telegram_document, send_telegram_message

    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=6)

    result = generate_report_pptx.func(start=start.isoformat(), end=end.isoformat())

    chat_ids = _target_chat_ids()
    if not chat_ids:
        logger.warning("No chat_ids configured/known for weekly deck — skipping send.")
        return

    async with httpx.AsyncClient() as http_client:
        if not result.startswith("FILE_PATH: "):
            # e.g. "No finalized sales between ... — nothing to build a deck from yet."
            logger.info(f"Weekly deck not generated: {result}")
            for chat_id in chat_ids:
                await send_telegram_message(http_client, chat_id, f"Weekly analysis deck: {result}")
            return

        file_path = result.split("FILE_PATH: ", 1)[1]
        for chat_id in chat_ids:
            await send_telegram_document(
                http_client, chat_id, file_path,
                caption=f"📊 Weekly sales analysis: {start.isoformat()} to {end.isoformat()}",
            )
        logger.info(f"Weekly deck sent to {len(chat_ids)} chat(s): {file_path}")


def start_scheduler() -> AsyncIOScheduler:
    """Call once from main.py's lifespan (see wiring note). Returns the
    scheduler so it can be cleanly shut down on app shutdown."""
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        send_weekly_analysis_deck,
        CronTrigger(day_of_week="mon", hour=3, minute=30),
        id="weekly_analysis_deck",
        replace_existing=True,
    )
    scheduler.start()
    return scheduler