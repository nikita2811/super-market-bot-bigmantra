# app/tools/preferences.py
from langchain_core.tools import tool
from app.db import SessionLocal
from app.model import Preference, gen_id
from sqlalchemy.exc import IntegrityError

DEFAULT_OWNER_ID = "default"  # single-owner shop for this assignment; see note below
SHOP_DETAILS_KEY = "shop_details"

@tool
def get_preference(key: str) -> str:
    """Look up a standing owner preference by key — e.g. 'default_payment_mode',
    'preferred_atta_brand', 'shop_name', 'gstin'. Use this whenever you need a
    default that the owner may have set previously (e.g. before assuming a
    payment mode wasn't specified, check get_preference('default_payment_mode')
    first). Returns 'not set' if the key doesn't exist yet — don't treat that
    as an error, just proceed without that default or ask the owner."""
    db = SessionLocal()
    try:
        pref = db.query(Preference).filter(
            Preference.owner_id == DEFAULT_OWNER_ID,
            Preference.key == key,
        ).first()
        if not pref:
            return f"Preference '{key}' is not set."
        return f"{key} = {pref.value}"
    finally:
        db.close()


@tool
def set_preference(key: str, value: str) -> str:
    """Store or update a standing owner preference — e.g. "always assume UPI
    unless I say cash" -> set_preference('default_payment_mode', 'UPI'), or
    "default atta = Aashirvaad 5kg" -> set_preference('preferred_atta_brand',
    'Aashirvaad 5kg'). This persists across chats and sessions — use it whenever
    the owner states a standing preference, not just a one-off instruction for
    the current bill."""
    db = SessionLocal()
    try:
        existing = db.query(Preference).filter(
            Preference.owner_id == DEFAULT_OWNER_ID,
            Preference.key == key,
        ).first()

        if existing:
            existing.value = value
            db.commit()
            return f"Updated preference: {key} = {value}"

        db.add(Preference(
            id=gen_id(),
            owner_id=DEFAULT_OWNER_ID,
            key=key,
            value=value,
        ))
        db.commit()
        return f"Saved preference: {key} = {value}"

    except IntegrityError:
        db.rollback()
        # race: two set_preference calls for the same key landed concurrently
        existing = db.query(Preference).filter(
            Preference.owner_id == DEFAULT_OWNER_ID,
            Preference.key == key,
        ).first()
        if existing:
            existing.value = value
            db.commit()
            return f"Updated preference: {key} = {value}"
        return "Failed to save preference due to a conflicting request — please retry."
    finally:
        db.close()



def _get_or_create_shop_row(db) -> Preference:
    row = db.query(Preference).filter(
        Preference.key == SHOP_DETAILS_KEY,
    ).first()
    if not row:
        row = Preference(
            id=gen_id(),
            owner_id=DEFAULT_OWNER_ID,
            key=SHOP_DETAILS_KEY,
            value="",
        )
        db.add(row)
        db.flush()
    return row


@tool
def set_shop_details(
    shop_name: str | None = None,
    phone: int | None = None,
    gstin: str | None = None,
    address: str | None = None,
) -> str:
    """Store or update the shop's own details used on invoices: shop_name,
    phone, gstin, address. Pass only the fields being changed — e.g. if the
    owner says "my GSTIN is 09ABCDE1234F1Z5", call
    set_shop_details(gstin='09ABCDE1234F1Z5') without touching the others.
    This persists across chats and is what generate_invoice_pdf reads to
    fill in the seller block on every invoice."""
    db = SessionLocal()
    try:
        row = _get_or_create_shop_row(db)

        updated = []
        if shop_name is not None:
            row.shop_name = shop_name
            updated.append("shop_name")
        if phone is not None:
            row.phone = int(phone)
            updated.append("phone")
        if gstin is not None:
            row.gstin = gstin
            updated.append("gstin")
        if address is not None:
            row.address = address
            updated.append("address")

        if not updated:
            return "No fields provided — nothing to update."

        db.commit()
        return f"Updated shop details: {', '.join(updated)}"
    finally:
        db.close()


@tool
def get_shop_details() -> str:
    """Look up the shop's stored details (shop_name, phone, gstin, address)
    used on invoices. Returns 'not set' for any field that hasn't been
    configured yet."""
    db = SessionLocal()
    try:
        row = db.query(Preference).filter(
            Preference.key == SHOP_DETAILS_KEY,
        ).first()
        if not row:
            return "Shop details are not set up yet."

        fields = {
            "shop_name": row.shop_name or "not set",
            "phone": row.phone or "not set",
            "gstin": row.gstin or "not set",
            "address": row.address or "not set",
        }
        return ", ".join(f"{k}={v}" for k, v in fields.items())
    finally:
        db.close()