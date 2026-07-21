from langchain_core.tools import tool
from app.db import SessionLocal
from app.model import Bill, BillItem, Product, StockMovement, BillStatus, MovementReason, gen_id
from datetime import datetime
from app.tools.guardrails import check_not_below_cost,check_oversell
from decimal import Decimal, ROUND_HALF_UP
from langchain_core.runnables import RunnableConfig
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("super-market-bot")

def _round2(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_gst(line_subtotal: float, gst_slab: float, is_intra_state: bool = True) -> dict:
    subtotal = Decimal(str(line_subtotal))
    slab = Decimal(str(gst_slab))
    total_tax = _round2(subtotal * slab / Decimal("100"))
    if is_intra_state:
        cgst = _round2(total_tax / 2)
        sgst = total_tax - cgst
    else:
        cgst = Decimal("0.00")
        sgst = Decimal("0.00")
    return {"cgst": cgst, "sgst": sgst, "line_total": _round2(subtotal + cgst + sgst)}

def _resolve_bill_item(bill, item_id_or_name: str):
    """Find a bill item by exact item_id first; fall back to matching product_name
    (case-insensitive substring) if the model passed a name instead of a real ID."""
    item = next((i for i in bill.items if i.id == item_id_or_name), None)
    if item:
        return item
    matches = [i for i in bill.items if item_id_or_name.lower() in i.product_name.lower()]
    if len(matches) == 1:
        return matches[0]
    return None 

@tool
def start_bill(customer_id: str | None = None, payment_mode: str | None = None,*, config: RunnableConfig) -> str:
    """Start a new draft bill. Call this when the owner begins cutting a bill
    (e.g. "make a bill: ..."). Returns the bill_id needed for all subsequent
    add_bill_item / finalize_bill calls in this transaction. customer_id is only
    needed if this sale goes on credit (khata) — otherwise leave it unset."""
    chat_id = config["configurable"]["chat_id"]
    db = SessionLocal()
    try:
        bill = Bill(
            id=gen_id(),
            chat_id=chat_id,  
            status=BillStatus.draft,
            customer_id=customer_id,
            payment_mode=payment_mode,
            subtotal=0,
            cgst=0,
            sgst=0,
            total=0,
        )
        db.add(bill)
        db.commit()
        return f"Started new bill (bill_id: {bill.id}). Add items to the bill."
    finally:
        db.close()


@tool
def add_bill_item(bill_id: str, sku_or_name: str, qty: float, force: bool = False) -> str:
    """Add an item to a draft bill by quantity. Enforces stock availability (oversell
    guard) and refuses to sell below the product's recorded cost unless force=True
    confirms it's intentional. Call this once per item the owner mentions."""
    db = SessionLocal()
    try:
        if qty <= 0:
            return "Quantity must be greater than zero"

        bill = db.query(Bill).filter(Bill.id == bill_id).first()
        if not bill:
            return f"No draft bill found with id '{bill_id}'"
        if bill.status != BillStatus.draft:
            return f"Bill {bill_id} is already {bill.status.value} — can't add items to it"

        product = db.query(Product).filter(
            (Product.sku == sku_or_name) | (Product.name.ilike(f"%{sku_or_name}%"))
        ).with_for_update().first()
        if not product:
            return f"No product found matching '{sku_or_name}'"

        # GUARDRAIL: don't sell below cost without explicit confirmation
        cost_check = check_not_below_cost(product, float(product.sell_price), force=force)
        if not cost_check.allowed:
            return cost_check.message

        already_on_bill = sum(float(i.qty) for i in bill.items if i.product_id == product.id)
        oversell_check = check_oversell(product, qty, already_reserved=already_on_bill)
        if not oversell_check.allowed:
            return oversell_check.message

        line_subtotal = _round2(float(product.sell_price) * qty)
        gst = calculate_gst(float(line_subtotal), float(product.gst_slab))

        item = BillItem(
            id=gen_id(), bill_id=bill.id, product_id=product.id, product_name=product.name,
            qty=qty, unit_price=product.sell_price, gst_slab=product.gst_slab,
            hsn_code=product.hsn_code, line_subtotal=line_subtotal,
            cgst_amt=gst["cgst"], sgst_amt=gst["sgst"], line_total=gst["line_total"],
        )
        db.add(item)
        bill.subtotal = float(bill.subtotal) + float(line_subtotal)
        bill.cgst = float(bill.cgst) + float(gst["cgst"])
        bill.sgst = float(bill.sgst) + float(gst["sgst"])
        bill.total = float(bill.total) + float(gst["line_total"])
        db.commit()

        return f"Added {qty} {product.unit} {product.name} @ ₹{product.sell_price} = ₹{gst['line_total']} (incl. GST) to bill {bill_id}"
    finally:
        db.close()


 


@tool
def remove_bill_item(bill_id: str, item_id: str) -> str:
    """Remove an ENTIRE line item from a draft bill — not a partial quantity
    reduction. Use this for phrases like "drop the butter", "remove the butter",
    "remove butter from the bill", or "remove item: butter" — anything that
    means take this product off the bill completely.

    If the owner instead names a quantity smaller than what's currently on the
    bill (e.g. "remove 2 packets of butter" when there are 5 on the bill), that
    means reduce the quantity, not delete the line — call update_bill_item with
    the new qty instead. Only call remove_bill_item if the requested quantity
    matches (or exceeds) what's already on the bill, or if no quantity is
    mentioned at all.

    item_id should be the exact item_id shown by get_bill_draft. Call
    get_bill_draft first if you don't already have it, or need to check the
    current quantity to decide between this and update_bill_item."""
    db = SessionLocal()
    try:
        bill = db.query(Bill).filter(Bill.id == bill_id).first()
        if not bill:
            return f"No draft bill found with id '{bill_id}'"
        if bill.status != BillStatus.draft:
            return f"Bill {bill_id} is already {bill.status.value} — can't edit it"

        item = _resolve_bill_item(bill, item_id)
        if not item:
            return f"No item matching '{item_id}' found on bill {bill_id} — call get_bill_draft to see current item_ids"

        bill.subtotal = float(bill.subtotal) - float(item.line_subtotal)
        bill.cgst = float(bill.cgst) - float(item.cgst_amt)
        bill.sgst = float(bill.sgst) - float(item.sgst_amt)
        bill.total = float(bill.total) - float(item.line_total)

        db.delete(item)
        db.commit()
        return f"Removed {item.product_name} from bill {bill_id}"
    finally:
        db.close()


@tool
def update_bill_item(bill_id: str, item_id: str, qty: float) -> str:
    """Change the quantity of an existing item on a draft bill (e.g. "make it 6 Maggi").
    Re-checks stock availability and recalculates GST for the new quantity.

    item_id should be the exact item_id shown by get_bill_draft. Call
    get_bill_draft first if you don't already have it."""
    db = SessionLocal()
    try:
        if qty <= 0:
            return "Quantity must be greater than zero — use remove_bill_item to remove it instead"

        bill = db.query(Bill).filter(Bill.id == bill_id).first()
        if not bill:
            return f"No draft bill found with id '{bill_id}'"
        if bill.status != BillStatus.draft:
            return f"Bill {bill_id} is already {bill.status.value} — can't edit it"

        item = _resolve_bill_item(bill, item_id)
        if not item:
            return f"No item matching '{item_id}' found on bill {bill_id} — call get_bill_draft to see current item_ids"

        product = db.query(Product).filter(Product.id == item.product_id).with_for_update().first()

        already_on_bill_other_items = sum(
            float(i.qty) for i in bill.items if i.product_id == product.id and i.id != item.id
        )
        if float(product.qty_on_hand) < already_on_bill_other_items + qty:
            available = float(product.qty_on_hand) - already_on_bill_other_items
            return f"Not enough stock: only {available} {product.unit} of {product.name} available — can't set qty to {qty}"

        bill.subtotal = float(bill.subtotal) - float(item.line_subtotal)
        bill.cgst = float(bill.cgst) - float(item.cgst_amt)
        bill.sgst = float(bill.sgst) - float(item.sgst_amt)
        bill.total = float(bill.total) - float(item.line_total)

        line_subtotal = _round2(float(item.unit_price) * qty)
        gst = calculate_gst(float(line_subtotal), float(item.gst_slab))

        item.qty = qty
        item.line_subtotal = line_subtotal
        item.cgst_amt = gst["cgst"]
        item.sgst_amt = gst["sgst"]
        item.line_total = gst["line_total"]

        bill.subtotal = float(bill.subtotal) + float(line_subtotal)
        bill.cgst = float(bill.cgst) + float(gst["cgst"])
        bill.sgst = float(bill.sgst) + float(gst["sgst"])
        bill.total = float(bill.total) + float(gst["line_total"])

        db.commit()
        return f"Updated {item.product_name} to qty {qty} — new line total ₹{gst['line_total']}"
    finally:
        db.close()


@tool
def get_bill_draft(bill_id: str) -> str:
    """Show the current running total and line items for a draft bill —
    use this to preview a bill before finalizing, or when the owner asks
    what's on the bill so far. Also use this to look up an item's item_id
    before calling remove_bill_item or update_bill_item."""
    db = SessionLocal()
    try:
        bill = db.query(Bill).filter(Bill.id == bill_id).first()
        if not bill:
            return f"No bill found with id '{bill_id}'"

        if not bill.items:
            return f"Bill {bill_id} is empty so far."

        lines = [
            f"- [item_id: {i.id}] {i.product_name} x{i.qty} @ ₹{i.unit_price} = ₹{i.line_total} "
            f"(GST {i.gst_slab}%: CGST ₹{i.cgst_amt} + SGST ₹{i.sgst_amt})"
            for i in bill.items
        ]
        return (
            f"Bill {bill_id} ({bill.status.value}):\n" + "\n".join(lines) +
            f"\nSubtotal: ₹{bill.subtotal} | CGST: ₹{bill.cgst} | SGST: ₹{bill.sgst} | Total: ₹{bill.total}"
        )
    finally:
        db.close()

  

      
      
@tool
def finalize_bill(bill_id: str, *, config: RunnableConfig) -> str:
    """Finalize a draft bill — decrements stock atomically and locks the bill.
    Call this only when the owner confirms the bill is complete (e.g. says
    "done", "finalize", "that's it"). Idempotency is handled automatically
    using the underlying Telegram update — no idempotency_key needed."""
    idempotency_key = config["configurable"]["update_id"]
    db = SessionLocal()
    try:
        existing_by_key = db.query(Bill).filter(Bill.idempotency_key == idempotency_key).with_for_update().first()
        if existing_by_key:
            return f"Bill already finalized under this request (bill_id: {existing_by_key.id}, total ₹{existing_by_key.total}) — not double-charging."

        bill = db.query(Bill).filter(Bill.id == bill_id).with_for_update().first()
        if not bill:
            return f"No bill found with id '{bill_id}'"
        if bill.status != BillStatus.draft:
            return f"Bill {bill_id} is already {bill.status.value} — can't finalize again"
        if not bill.items:
            return f"Bill {bill_id} has no items — nothing to finalize"

        for item in bill.items:
            product = db.query(Product).filter(Product.id == item.product_id).with_for_update().first()
            if float(product.qty_on_hand) < float(item.qty):
                db.rollback()
                return f"Cannot finalize: {product.name} now only has {product.qty_on_hand} {product.unit} in stock, but bill requires {item.qty}"

        for item in bill.items:
            db.execute(
                text("UPDATE products SET qty_on_hand = qty_on_hand - :qty WHERE id = :pid"),
                {"qty": float(item.qty), "pid": item.product_id},
            )
            db.add(StockMovement(
                id=gen_id(),
                product_id=item.product_id,
                delta=-float(item.qty),
                reason=MovementReason.sale,
                ref_id=bill.id,
                created_at=datetime.utcnow(),
            ))

        bill.status = BillStatus.finalized
        bill.idempotency_key = idempotency_key
        bill.finalized_at = datetime.utcnow()
        db.commit()

        return f"Bill {bill_id} finalized. Total: ₹{bill.total} ({bill.payment_mode or 'payment mode not set'})"

    except IntegrityError:
        db.rollback()
        existing_by_key = db.query(Bill).filter(Bill.idempotency_key == idempotency_key).first()
        if existing_by_key:
            return f"Bill already finalized under this request (bill_id: {existing_by_key.id}) — not double-charging."
        return "Finalize failed due to a conflicting request — please retry."
    finally:
        db.close()

        
@tool
def cancel_bill(bill_id: str) -> str:
    """Cancel a FINALIZED bill and reverse its stock decrement. Refuses to void a
    draft bill (nothing to reverse) or a bill that's already void. Use this only
    when the owner explicitly wants to cancel a completed sale, not to edit a draft
    (use remove_bill_item / update_bill_item for drafts instead)."""
    db = SessionLocal()
    try:
        bill = db.query(Bill).filter(Bill.id == bill_id).first()
        if not bill:
            return f"No bill found with id '{bill_id}'"
        if bill.status == BillStatus.draft:
            return f"Bill {bill_id} is still a draft — nothing to cancel. Use remove_bill_item to edit it."
        if bill.status == BillStatus.cancel:
            return f"Bill {bill_id} is already cancel."

        for item in bill.items:
            db.execute(
                text("UPDATE products SET qty_on_hand = qty_on_hand + :qty WHERE id = :pid"),
                {"qty": float(item.qty), "pid": item.product_id},
            )
            db.add(StockMovement(
                id=gen_id(),
                product_id=item.product_id,
                delta=float(item.qty),
                reason=MovementReason.adjustment,
                ref_id=bill.id,
                created_at=datetime.utcnow(),
            ))

        bill.status = BillStatus.cancel
        db.commit()
        return f"Bill {bill_id} cancelled.Stock for {len(bill.items)} item(s) reversed."
    finally:
        db.close()



