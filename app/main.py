import logging
import httpx
from fastapi import FastAPI, Request, Header, HTTPException
from app.config import TELEGRAM_WEBHOOK_SECRET, TELEGRAM_BOT_TOKEN
from app.db import SessionLocal
from app.model import ProcessedUpdate,ChatSession
from app.bot import handle_telegram_message  # the function from agent.py/bot.py
from contextlib import asynccontextmanager
from app.agent import init_checkpointer,build_agent
import os
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.khata_reminders import send_khata_reminders
from app.deck_scheduler import start_scheduler
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("super-market-bot")

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_khata_reminders, "cron", hour=10)
    scheduler.start()

    weekly_deck_scheduler = start_scheduler()
    with init_checkpointer() as checkpointer:
        app.state.agent = build_agent(checkpointer)
        yield
    weekly_deck_scheduler.shutdown()
    scheduler.shutdown()
    
app = FastAPI(lifespan=lifespan)

WEBHOOK_PATH = f"/webhook/{TELEGRAM_BOT_TOKEN}"
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
TELEGRAM_FILE_API = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TRANSCRIBE_MODEL = os.getenv("AGENT_MODEL")

MIME_TYPES = {
    ".pdf": "application/pdf",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def _chat_session_row(db, chat_id: str) -> None:
    existing = db.query(ChatSession).filter(ChatSession.chat_id == chat_id).first()
    if not existing:
        db.add(ChatSession(chat_id=chat_id, owner_id="default", current_draft_bill_id=None))
        db.commit()


async def send_telegram_message(http_client: httpx.AsyncClient, chat_id: str, text: str):
    await http_client.post(
        f"{TELEGRAM_API}/sendMessage",
        json={"chat_id": chat_id, "text": text},
    )


async def send_telegram_document(
    http_client: httpx.AsyncClient,
    chat_id: str,
    file_path: str,
    caption: str | None = None,
):
    """Send any document (PDF, PPTX, etc.) to a Telegram chat via sendDocument."""
    if not os.path.exists(file_path):
        logger.error(f"File path does not exist: {file_path}")
        return

    filename = os.path.basename(file_path)
    ext = os.path.splitext(filename)[1].lower()
    mime_type = MIME_TYPES.get(ext, "application/octet-stream")

    with open(file_path, "rb") as f:
        files = {"document": (filename, f, mime_type)}
        data = {"chat_id": chat_id}
        if caption:
            data["caption"] = caption

        response = await http_client.post(
            f"{TELEGRAM_API}/sendDocument",
            data=data,
            files=files,
        )

    if response.status_code != 200 or not response.json().get("ok", False):
        logger.error(f"Failed to send {ext} file to {chat_id}: {response.text}")


async def _download_telegram_file(http_client: httpx.AsyncClient, file_id: str) -> bytes:
    """Resolve a Telegram file_id to bytes via getFile + file download."""
    resp = await http_client.get(f"{TELEGRAM_API}/getFile", params={"file_id": file_id})
    resp.raise_for_status()
    file_path = resp.json()["result"]["file_path"]

    file_resp = await http_client.get(f"{TELEGRAM_FILE_API}/{file_path}")
    file_resp.raise_for_status()
    return file_resp.content


async def transcribe_voice_note(http_client: httpx.AsyncClient, audio_bytes: bytes, mime_type: str) -> str:
    """Send voice note audio to Gemini for transcription, return plain text."""
    import base64

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": "Transcribe this audio exactly. Return only the transcribed text, nothing else."},
                    {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(audio_bytes).decode()}},
                ]
            }
        ]
    }

    resp = await http_client.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{TRANSCRIBE_MODEL}:generateContent",
        params={"key": GEMINI_API_KEY},
        json=payload,
        timeout=30.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


async def _process_and_reply(request:Request,chat_id: str, text: str,update_id:str, http_client: httpx.AsyncClient):
    """Run the agent on `text` and send back whatever it produces (message + optional file)."""
    result = await handle_telegram_message(request,chat_id, text,update_id)

    if isinstance(result, dict):
        reply_text = result.get("text", "")
        file_path = result.get("file_path") or result.get("pdf_path")  # backward-compat with old key
    else:
        reply_text = result
        file_path = None

    if reply_text:
        await send_telegram_message(http_client, chat_id, reply_text)
    if file_path:
        ext = os.path.splitext(file_path)[1].lower()
        caption = "Here's your invoice 🧾" if ext == ".pdf" else "Here's your file 📎"
        await send_telegram_document(http_client, chat_id, file_path, caption=caption)


@app.post(WEBHOOK_PATH)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    if x_telegram_bot_api_secret_token != TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid secret token")

    update = await request.json()
    update_id = str(update.get("update_id"))

    db = SessionLocal()
    try:
        already_seen = db.query(ProcessedUpdate).filter(
            ProcessedUpdate.update_id == update_id
        ).first()
        if already_seen:
            logger.info(f"Duplicate update {update_id}, skipping")
            return {"ok": True}

        db.add(ProcessedUpdate(update_id=update_id))
        db.commit()
    finally:
        db.close()

    message = update.get("message")
    if not message:
        return {"ok": True}

    chat_id = str(message["chat"]["id"])

    db = SessionLocal()
    try:
        _chat_session_row(db, chat_id)
    finally:
        db.close()

    async with httpx.AsyncClient() as http_client:
        if "text" in message:
            text = message["text"]
            logger.info(f"Message from {chat_id}: {text}")
            await _process_and_reply(request,chat_id, text,update_id, http_client)

        elif "voice" in message:
            logger.info(f"Voice note from {chat_id}")
            file_id = message["voice"]["file_id"]
            mime_type = message["voice"].get("mime_type", "audio/ogg")

            try:
                audio_bytes = await _download_telegram_file(http_client, file_id)
                transcript = await transcribe_voice_note(http_client, audio_bytes, mime_type)
                logger.info(f"Transcribed voice from {chat_id}: {transcript}")
            except Exception as e:
                logger.error(f"Voice transcription failed for {chat_id}: {e}")
                await send_telegram_message(
                    http_client, chat_id, "Sorry, I couldn't understand that voice note — could you type it instead?"
                )
                return {"ok": True}

            if not transcript:
                await send_telegram_message(http_client, chat_id, "I couldn't make out anything in that voice note.")
                return {"ok": True}

            await _process_and_reply(request,chat_id, transcript,update_id, http_client)

    return {"ok": True}