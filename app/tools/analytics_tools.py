import json
from datetime import datetime, date, time, timedelta
from decimal import Decimal
from langchain_core.tools import tool
from app.db import SessionLocal
from app.model import Bill, BillItem, BillStatus, DailyClosure,gen_id
from sqlalchemy.exc import IntegrityError


IST_OFFSET = timedelta(hours=5, minutes=30)


def _today_ist() -> date:
    return (datetime.utcnow() + IST_OFFSET).date()


def _parse_date(date_str: str) -> date | None:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None


def _day_bounds_utc(target_date: date) -> tuple[datetime, datetime]:
    """[start, end) UTC range covering one IST calendar day."""
    start_ist = datetime.combine(target_date, time.min)
    start_utc = start_ist - IST_OFFSET
    return start_utc, start_utc + timedelta(days=1)


def _compute_live_day(db, target_date: date) -> dict:
    """Recompute a day's numbers from finalized bills — used when the day
    hasn't been closed yet. Returns the same shape as a frozen DailyClosure row."""
    start_utc, end_utc = _day_bounds_utc(target_date)
    bills = db.query(Bill).filter(
        Bill.status == BillStatus.finalized,
        Bill.finalized_at >= start_utc,
        Bill.finalized_at < end_utc,
    ).all()

    total_sales = sum((Decimal(str(b.total)) for b in bills), Decimal("0"))
    total_tax = sum((Decimal(str(b.cgst)) + Decimal(str(b.sgst)) for b in bills), Decimal("0"))

    split = {"cash": Decimal("0"), "upi": Decimal("0"), "card": Decimal("0"), "other": Decimal("0")}
    for b in bills:
        mode = (b.payment_mode or "other").lower()
        key = mode if mode in ("cash", "upi", "card") else "other"
        split[key] += Decimal(str(b.total))

    item_totals: dict[str, tuple[Decimal, Decimal]] = {}
    if bills:
        items = db.query(BillItem).filter(BillItem.bill_id.in_([b.id for b in bills])).all()
        for i in items:
            qty, revenue = item_totals.get(i.product_name, (Decimal("0"), Decimal("0")))
            item_totals[i.product_name] = (qty + Decimal(str(i.qty)), revenue + Decimal(str(i.line_total)))

    top_items = sorted(item_totals.items(), key=lambda kv: kv[1][0], reverse=True)[:5]

    return {
        "total_sales": total_sales,
        "total_tax": total_tax,
        "cash_total": split["cash"],
        "upi_total": split["upi"],
        "card_total": split["card"],
        "other_total": split["other"],
        "bill_count": len(bills),
        "top_items": [(name, qty, revenue) for name, (qty, revenue) in top_items],
    }


def _format_summary(target_date: date, data: dict, closed: bool) -> str:
    top_items_str = ", ".join(f"{name} ({qty} units, ₹{revenue})" for name, qty, revenue in data["top_items"]) or "none"
    return (
        f"Summary for {target_date.isoformat()}{' (CLOSED)' if closed else ''}:\n"
        f"Total sales: ₹{data['total_sales']}\n"
        f"Tax collected: ₹{data['total_tax']}\n"
        f"Payment split — Cash: ₹{data['cash_total']} | UPI: ₹{data['upi_total']} | Card: ₹{data['card_total']} | Other: ₹{data['other_total']}\n"
        f"Bills: {data['bill_count']}\n"
        f"Top items: {top_items_str}"
    )



@tool
def get_daily_summary(date: str | None = None) -> str:
    """Show a day's sales summary: total sales, tax collected, cash/UPI/card
    split, and top-selling items. date is optional, format YYYY-MM-DD — omit it
    for today. If the day has already been closed via close_day, this returns
    the locked numbers rather than recomputing live, so it can't drift even if
    a bill from that day is voided afterwards."""
    db = SessionLocal()
    try:
        if date:
            target_date = _parse_date(date)
            if not target_date:
                return f"Couldn't parse date '{date}' — use YYYY-MM-DD."
        else:
            target_date = _today_ist()

        closure = db.query(DailyClosure).filter(DailyClosure.closure_date == target_date).first()
        if closure:
            data = {
                "total_sales": Decimal(str(closure.total_sales)),
                "total_tax": Decimal(str(closure.total_tax)),
                "cash_total": Decimal(str(closure.cash_total)),
                "upi_total": Decimal(str(closure.upi_total)),
                "card_total": Decimal(str(closure.card_total)),
                "other_total": Decimal(str(closure.other_total)),
                "bill_count": closure.bill_count,
                "top_items": json.loads(closure.top_items_json or "[]"),
            }
            return _format_summary(target_date, data, closed=True)

        data = _compute_live_day(db, target_date)
        if data["bill_count"] == 0:
            return f"No finalized sales for {target_date.isoformat()} yet."
        return _format_summary(target_date, data, closed=False)
    finally:
        db.close()




@tool
def close_day(date: str | None = None, force: bool = False) -> str:
    """Lock a day's sales numbers so they can't shift later — this is what
    get_daily_summary and get_sales_range read from once a day is closed.
    date is optional, format YYYY-MM-DD — omit it for today. Idempotent: closing
    an already-closed day just returns the existing locked numbers, never
    recomputes or duplicates them. Refuses to close if there are still open
    draft bills from that day (they'd be silently excluded from the total)
    unless force=True explicitly confirms that's intended."""
    db = SessionLocal()
    try:
        if date:
            target_date = _parse_date(date)
            if not target_date:
                return f"Couldn't parse date '{date}' — use YYYY-MM-DD."
        else:
            target_date = _today_ist()

        existing = db.query(DailyClosure).filter(DailyClosure.closure_date == target_date).first()
        if existing:
            return (
                f"{target_date.isoformat()} was already closed at {existing.closed_at} — "
                f"total sales ₹{existing.total_sales}, tax ₹{existing.total_tax}. Not re-closing."
            )

       
        start_utc, end_utc = _day_bounds_utc(target_date)
        open_drafts = db.query(Bill).filter(
            Bill.status == BillStatus.draft,
            Bill.created_at >= start_utc,
            Bill.created_at < end_utc,
        ).all()
        if open_drafts and not force:
            return (
                f"{len(open_drafts)} draft bill(s) from {target_date.isoformat()} are still open "
                f"(not finalized or voided) — closing now would leave them out of today's numbers. "
                f"Finalize or void them first, or call again with force=True to close anyway."
            )

        data = _compute_live_day(db, target_date)

        closure = DailyClosure(
            id=gen_id,  
            closure_date=target_date,
            total_sales=float(data["total_sales"]),
            total_tax=float(data["total_tax"]),
            cash_total=float(data["cash_total"]),
            upi_total=float(data["upi_total"]),
            card_total=float(data["card_total"]),
            other_total=float(data["other_total"]),
            bill_count=data["bill_count"],
            top_items_json=json.dumps(data["top_items"], default=str),
            closed_at=datetime.utcnow(),
        )
        db.add(closure)
        db.commit()

        note = f" ({len(open_drafts)} open draft(s) excluded, force=True)" if open_drafts else ""
        return (
            f"{target_date.isoformat()} closed. Total sales ₹{data['total_sales']}, "
            f"tax ₹{data['total_tax']}, {data['bill_count']} bill(s).{note}"
        )

    except IntegrityError:
        db.rollback()
        existing = db.query(DailyClosure).filter(DailyClosure.closure_date == target_date).first()
        if existing:
            return f"{target_date.isoformat()} was already closed (concurrent request) — total sales ₹{existing.total_sales}."
        return "Closing failed due to a conflicting request — please retry."
    finally:
        db.close()




@tool
def get_sales_range(start: str, end: str) -> str:
    """Pull sales data across a date range (inclusive), for building a
    weekly/monthly report: per-day totals, tax, and bill counts, plus
    range-wide totals and top items. Dates are format YYYY-MM-DD. Days already
    closed via close_day use the locked numbers; days not yet closed are
    computed live from finalized bills."""
    db = SessionLocal()
    try:
        start_date = _parse_date(start)
        end_date = _parse_date(end)
        if not start_date or not end_date:
            return "Couldn't parse one of the dates — use YYYY-MM-DD for both start and end."
        if start_date > end_date:
            return f"start ({start}) is after end ({end}) — did you mean to swap them?"
        if (end_date - start_date).days > 366:
            return "Range is over a year — narrow it down for a meaningful deck."

        lines = []
        range_sales = Decimal("0")
        range_tax = Decimal("0")
        range_bill_count = 0
        item_totals: dict[str, tuple[Decimal, Decimal]] = {}

        current = start_date
        while current <= end_date:
            closure = db.query(DailyClosure).filter(DailyClosure.closure_date == current).first()
            if closure:
                day_sales = Decimal(str(closure.total_sales))
                day_tax = Decimal(str(closure.total_tax))
                day_count = closure.bill_count
                for name, qty, revenue in json.loads(closure.top_items_json or "[]"):
                    q, r = item_totals.get(name, (Decimal("0"), Decimal("0")))
                    item_totals[name] = (q + Decimal(str(qty)), r + Decimal(str(revenue)))
            else:
                day_data = _compute_live_day(db, current)
                day_sales = day_data["total_sales"]
                day_tax = day_data["total_tax"]
                day_count = day_data["bill_count"]
                for name, qty, revenue in day_data["top_items"]:
                    q, r = item_totals.get(name, (Decimal("0"), Decimal("0")))
                    item_totals[name] = (q + Decimal(str(qty)), r + Decimal(str(revenue)))

            lines.append(
                f"{current.isoformat()}: ₹{day_sales} sales, ₹{day_tax} tax, {day_count} bill(s)"
                f"{' (closed)' if closure else ''}"
            )
            range_sales += day_sales
            range_tax += day_tax
            range_bill_count += day_count
            current += timedelta(days=1)

        top_items = sorted(item_totals.items(), key=lambda kv: kv[1][0], reverse=True)[:5]
        top_items_str = ", ".join(f"{name} ({qty} units, ₹{revenue})" for name, (qty, revenue) in top_items) or "none"

        return (
            f"Sales from {start_date.isoformat()} to {end_date.isoformat()}:\n"
            + "\n".join(lines)
            + f"\n\nRange total: ₹{range_sales} sales | ₹{range_tax} tax | {range_bill_count} bill(s)"
            + f"\nTop items across range: {top_items_str}"
        )
    finally:
        db.close()