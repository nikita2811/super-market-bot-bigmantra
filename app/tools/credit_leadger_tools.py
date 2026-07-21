from datetime import datetime
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from sqlalchemy.exc import IntegrityError
from app.db import SessionLocal
from app.model import Customer, AccountTransaction, AccountType, gen_id
from app.tools.guardrails import check_account_settlement_is_valid


@tool
def get_or_create_customer(name: str, phone: str | None = None,*,config:RunnableConfig) -> str:
    """Look up a customer by name, or create them if they don't exist yet.
    Use this before add_credit, record_payment, or get_balance if you're not
    sure whether the customer already exists — it's safe to call even if they do,
    it won't create a duplicate. Matches by name (case-insensitive); if phone is
    given and there's an ambiguous match, use it to disambiguate."""
    db = SessionLocal()
    chat_id = config["configurable"]["chat_id"]
    try:
        query = db.query(Customer).filter(Customer.name.ilike(f"%{name.strip()}%"))
        if phone:
            query = query.filter(Customer.phone == phone)
        matches = query.all()

        if len(matches) == 1:
            c = matches[0]
            return f"Customer '{c.name}' (customer_id: {c.id}), current balance: ₹{c.account_balance}"
        if len(matches) > 1:
            lines = "\n".join(f"- {c.name} (id: {c.id}, phone: {c.phone or 'none'})" for c in matches)
            return f"Multiple customers match '{name}' — please confirm which one:\n{lines}"

        customer = Customer(
            id=gen_id(),
            name=name.strip(),
            phone=phone,
            account_balance=0,
            chat_id=chat_id,
        )
        db.add(customer)
        db.commit()
        return f"New customer created: '{customer.name}' (customer_id: {customer.id}), balance: ₹0"
    finally:
        db.close()


@tool
def add_credit(customer_id: str, amount: float, ref_bill_id: str | None = None, *, config: RunnableConfig) -> str:
    """Add an amount to a customer's khata (credit) balance — e.g. "put ₹500 on
    Ramesh's credit". Use get_or_create_customer first if you only have a name,
    not a customer_id. ref_bill_id is optional — pass it if this credit is tied
    to a specific bill being put on account rather than paid immediately."""
    idempotency_key = config["configurable"]["update_id"]
    db = SessionLocal()
    try:
        existing = db.query(AccountTransaction).filter(
            AccountTransaction.idempotency_key == idempotency_key
        ).first()
        if existing:
            return f"This credit was already recorded (₹{existing.amount}) — not double-adding."

        if amount <= 0:
            return "Credit amount must be greater than zero"

        customer = db.query(Customer).filter(Customer.id == customer_id).with_for_update().first()
        if not customer:
            return f"No customer found with id '{customer_id}' — use get_or_create_customer first"

        customer.account_balance = float(customer.account_balance) + amount

        db.add(AccountTransaction(
            id=gen_id(),
            customer_id=customer.id,
            type=AccountType.credit_sale,
            amount=amount,
            ref_bill_id=ref_bill_id,
            idempotency_key=idempotency_key,
            created_at=datetime.utcnow(),
        ))
        db.commit()

        return f"Added ₹{amount} credit for {customer.name}. New balance: ₹{customer.account_balance}"

    except IntegrityError:
        db.rollback()
        existing = db.query(AccountTransaction).filter(
            AccountTransaction.idempotency_key == idempotency_key
        ).first()
        if existing:
            return f"This credit was already recorded (₹{existing.amount}) — not double-adding."
        return "Failed due to a conflicting request — please retry."
    finally:
        db.close()


@tool
def record_payment(customer_id: str, amount: float, *, config: RunnableConfig) -> str:
    """Record a payment from a customer against their khata balance — e.g.
    "Ramesh paid ₹300". Use get_or_create_customer first if you only have a name.
    Refuses if the payment would take the balance negative — confirm with the
    owner if the customer is overpaying (e.g. clearing an old balance and adding
    extra credit) rather than silently allowing it."""
    idempotency_key = config["configurable"]["update_id"]
    db = SessionLocal()
    try:
        existing = db.query(AccountTransaction).filter(
            AccountTransaction.idempotency_key == idempotency_key
        ).first()
        if existing:
            return f"This payment was already recorded (₹{existing.amount}) — not double-charging."

        if amount <= 0:
            return "Payment amount must be greater than zero"
        
        settlement_check = check_account_settlement_is_valid(db, customer_id, amount)
        if not settlement_check.allowed:
            return settlement_check.message

        customer = db.query(Customer).filter(Customer.id == customer_id).with_for_update().first()
        if not customer:
            return f"No customer found with id '{customer_id}' — use get_or_create_customer first"

        if amount > float(customer.account_balance):
            return (
                f"{customer.name}'s current balance is only ₹{customer.account_balance} — "
                f"₹{amount} would overpay by ₹{amount - float(customer.account_balance)}. "
                f"Confirm with the owner before recording this (they may want to record "
                f"only ₹{customer.account_balance}, or intentionally leave a credit balance)."
            )

        customer.account_balance = float(customer.account_balance) - amount

        db.add(AccountTransaction(
            id=gen_id(),
            customer_id=customer.id,
            type=AccountType.payment,
            amount=amount,
            ref_bill_id=None,
            idempotency_key=idempotency_key,
            created_at=datetime.utcnow(),
        ))
        db.commit()

        return f"Recorded ₹{amount} payment from {customer.name}. New balance: ₹{customer.account_balance}"

    except IntegrityError:
        db.rollback()
        existing = db.query(AccountTransaction).filter(
            AccountTransaction.idempotency_key == idempotency_key
        ).first()
        if existing:
            return f"This payment was already recorded (₹{existing.amount}) — not double-charging."
        return "Failed due to a conflicting request — please retry."
    finally:
        db.close()


@tool
def get_balance(customer_id: str) -> str:
    """Look up a customer's current khata (credit) balance — e.g. "what's Ramesh's
    balance?". Use get_or_create_customer first if you only have a name, not a
    customer_id."""
    db = SessionLocal()
    try:
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if not customer:
            return f"No customer found with id '{customer_id}'"
        return f"{customer.name}'s balance: ₹{customer.account_balance}"
    finally:
        db.close()