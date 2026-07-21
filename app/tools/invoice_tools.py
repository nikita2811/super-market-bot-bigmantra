import os
from langchain_core.tools import tool
from app.db import SessionLocal
from app.model import Bill, BillStatus, Product, Preference
from app.invoice_template import render_gst_invoice
import logging

INVOICE_OUTPUT_DIR = os.environ.get("INVOICE_OUTPUT_DIR", "/tmp/invoices")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("super-market-bot")

@tool
def generate_invoice_pdf(bill_id: str) -> str:
    """Generate a GST-correct tax invoice PDF for a bill. Only works on
    finalized (or voided) bills — a draft has no locked totals to invoice yet.
    Returns the file path of the generated PDF so it can be sent to the owner
    (e.g. via Telegram sendDocument)."""
    db = SessionLocal()
    try:
        bill = db.query(Bill).filter(Bill.id == bill_id).first()
        if not bill:
            return f"No bill found with id '{bill_id}'"
        if bill.status == BillStatus.draft:
            return f"Bill {bill_id} is still a draft — finalize it first before generating an invoice."

        items_data = []
        for item in bill.items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            unit = product.unit if product else ""
            items_data.append({
                "name": item.product_name,
                "hsn": item.hsn_code or "",
                "qty": item.qty,
                "unit": unit,
                "unit_price": item.unit_price,
                "taxable_value": item.line_subtotal,
                "gst_rate": item.gst_slab,
                "cgst": item.cgst_amt,
                "sgst": item.sgst_amt,
                "line_total": item.line_total,
            })

        customer = None
        if bill.customer_id:
            try:
                from app.model import Customer
                cust = db.query(Customer).filter(Customer.id == bill.customer_id).first()
                if cust:
                    customer = {
                        "name": getattr(cust, "name", bill.customer_id),
                        "gstin": getattr(cust, "gstin", None),
                    }
            except ImportError:
                customer = {"name": bill.customer_id, "gstin": None}

        
        prefs = db.query(Preference).filter(
            Preference.key == "shop_details",
        ).first()
        if not prefs:
            return "Shop preferences are not set up yet — add your shop details before generating invoices."

        seller = {
            "name": getattr(prefs, "shop_name", "") or "",
            "address": getattr(prefs, "address", "") or "",
            "gstin": getattr(prefs, "gstin", "") or "",
            "phone": getattr(prefs, "phone", "") or "",
        }

        invoice_data = {
            "seller": seller,
            "invoice_no": bill.id,
            "invoice_date": (bill.finalized_at or bill.created_at).strftime("%d %b %Y"),
            "status_note": "CANCELLED" if bill.status == BillStatus.cancel else None,
            "customer": customer,
            "payment_mode": bill.payment_mode,
            "items": items_data,
            "totals": {
                "subtotal": bill.subtotal,
                "cgst": bill.cgst,
                "sgst": bill.sgst,
                "total": bill.total,
            },
        }

        os.makedirs(INVOICE_OUTPUT_DIR, exist_ok=True)
        output_path = os.path.join(INVOICE_OUTPUT_DIR, f"invoice_{bill.id}.pdf")
        render_gst_invoice(output_path, invoice_data)
        logger.info(f"Saved to: {output_path}")
        logger.info(f"Exists immediately after save: {os.path.exists(output_path)}")

        return f"Invoice generated. FILE_PATH: {output_path}"
    finally:
        db.close()