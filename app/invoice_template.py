from decimal import Decimal
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.enums import TA_RIGHT, TA_CENTER
import os


_INDIAN_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
                "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
                "Seventeen", "Eighteen", "Nineteen"]
_INDIAN_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two_digit_words(n: int) -> str:
    if n < 20:
        return _INDIAN_ONES[n]
    return (_INDIAN_TENS[n // 10] + (f" {_INDIAN_ONES[n % 10]}" if n % 10 else "")).strip()


def _three_digit_words(n: int) -> str:
    if n >= 100:
        rest = n % 100
        return f"{_INDIAN_ONES[n // 100]} Hundred" + (f" {_two_digit_words(rest)}" if rest else "")
    return _two_digit_words(n)


def amount_in_words(amount) -> str:
    
    amount = Decimal(str(amount)).quantize(Decimal("0.01"))
    rupees = int(amount)
    paise = int((amount - rupees) * 100)

    if rupees == 0:
        rupee_words = "Zero"
    else:
        parts = []
        crore, rupees = divmod(rupees, 10_000_000)
        lakh, rupees = divmod(rupees, 100_000)
        thousand, rupees = divmod(rupees, 1000)
        hundred = rupees

        if crore:
            parts.append(f"{_three_digit_words(crore)} Crore")
        if lakh:
            parts.append(f"{_three_digit_words(lakh)} Lakh")
        if thousand:
            parts.append(f"{_three_digit_words(thousand)} Thousand")
        if hundred:
            parts.append(_three_digit_words(hundred))
        rupee_words = " ".join(parts)

    words = f"{rupee_words} Rupees"
    if paise:
        words += f" and {_two_digit_words(paise)} Paise"
    return words + " Only"


def render_gst_invoice(output_path: str, invoice_data: dict) -> None:
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("RightAlign", parent=styles["Normal"], alignment=TA_RIGHT))
    styles.add(ParagraphStyle("Center", parent=styles["Normal"], alignment=TA_CENTER))
    styles.add(ParagraphStyle("InvoiceTitle", parent=styles["Title"], fontSize=16, spaceAfter=2))
    styles.add(ParagraphStyle("SellerName", parent=styles["Normal"], fontSize=13, leading=16))
    styles.add(ParagraphStyle("Small", parent=styles["Normal"], fontSize=8, textColor=colors.grey))

    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        topMargin=15 * mm, bottomMargin=15 * mm, leftMargin=15 * mm, rightMargin=15 * mm,
    )
    story = []

    seller = invoice_data["seller"]
    story.append(Paragraph(seller["name"], styles["SellerName"]))
    story.append(Paragraph(seller["address"], styles["Normal"]))
    story.append(Paragraph(f"GSTIN: {seller['gstin']} | Phone: {seller['phone']}", styles["Normal"]))
    story.append(Spacer(1, 8))

    title = "TAX INVOICE"
    if invoice_data.get("status_note"):
        title += f" — {invoice_data['status_note']}"
    story.append(Paragraph(title, styles["InvoiceTitle"]))
    story.append(Spacer(1, 4))

    meta_rows = [
        ["Invoice No:", invoice_data["invoice_no"], "Invoice Date:", invoice_data["invoice_date"]],
        ["Payment Mode:", invoice_data.get("payment_mode") or "—", "", ""],
    ]
    meta_table = Table(meta_rows, colWidths=[80, 160, 80, 160])
    meta_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 8))

    customer = invoice_data.get("customer")
    if customer:
        story.append(Paragraph(f"<b>Bill To:</b> {customer['name']}"
                                + (f" (GSTIN: {customer['gstin']})" if customer.get("gstin") else ""),
                                styles["Normal"]))
    else:
        story.append(Paragraph("<b>Bill To:</b> Cash sale / walk-in customer", styles["Normal"]))
    story.append(Spacer(1, 10))

    header = ["Sr", "Item", "HSN", "Qty", "Rate", "Taxable\nValue", "CGST", "SGST", "Total"]
    rows = [header]
    for idx, item in enumerate(invoice_data["items"], start=1):
        rows.append([
            str(idx),
            item["name"],
            item["hsn"],
            f"{item['qty']:g} {item['unit']}",
            f"₹{Decimal(str(item['unit_price'])):.2f}",
            f"₹{Decimal(str(item['taxable_value'])):.2f}",
            f"₹{Decimal(str(item['cgst'])):.2f}\n({Decimal(str(item['gst_rate'])) / 2:g}%)",
            f"₹{Decimal(str(item['sgst'])):.2f}\n({Decimal(str(item['gst_rate'])) / 2:g}%)",
            f"₹{Decimal(str(item['line_total'])):.2f}",
        ])

    totals = invoice_data["totals"]
    rows.append([
        "", "", "", "", "",
        f"₹{Decimal(str(totals['subtotal'])):.2f}",
        f"₹{Decimal(str(totals['cgst'])):.2f}",
        f"₹{Decimal(str(totals['sgst'])):.2f}",
        f"₹{Decimal(str(totals['total'])):.2f}",
    ])

    col_widths = [22, 110, 45, 50, 45, 55, 45, 45, 55]
    item_table = Table(rows, colWidths=col_widths, repeatRows=1)
    item_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -2), 0.5, colors.HexColor("#CCCCCC")),
        ("LINEABOVE", (0, -1), (-1, -1), 1, colors.black),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(item_table)
    story.append(Spacer(1, 10))

    story.append(Paragraph(f"<b>Amount in words:</b> {amount_in_words(totals['total'])}", styles["Normal"]))
    story.append(Spacer(1, 20))
    story.append(Paragraph("This is a computer-generated invoice.", styles["Small"]))

    doc.build(story)
    print(f"PDF exists: {os.path.exists(output_path)}")
    print(f"PDF size: {os.path.getsize(output_path) if os.path.exists(output_path) else 0}")