import httpx
from app.db import SessionLocal
from app.model import Customer, ChatSession
from app.config import TELEGRAM_API_URL

TELEGRAM_API = TELEGRAM_API_URL


async def send_khata_reminders():
    """Daily cron job: notify the shop owner (not the credit customers
    themselves — they aren't Telegram users of this bot) about which
    customers still have an outstanding khata balance.
    """
    db = SessionLocal()
    try:
        overdue = (
            db.query(Customer)
            .filter(Customer.account_balance > 0)
            .order_by(Customer.account_balance.desc())
            .all()
        )
        if not overdue:
            return

        lines = [f"- {c.name}: ₹{c.account_balance}" for c in overdue]
        total = sum(c.account_balance for c in overdue)
        text = (
            "Khata reminder — outstanding customer balances:\n"
            + "\n".join(lines)
            + f"\n\nTotal outstanding: ₹{total}"
        )

        owner_chat_ids = {row.chat_id for row in db.query(ChatSession).all()}
        if not owner_chat_ids:
            return

        async with httpx.AsyncClient(timeout=10) as http_client:
            for chat_id in owner_chat_ids:
                await http_client.post(
                    f"{TELEGRAM_API}/sendMessage",
                    json={"chat_id": chat_id, "text": text},
                )
    finally:
        db.close()