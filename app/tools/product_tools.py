from langchain_core.tools import tool
from app.db import SessionLocal
from app.model import Product, StockMovement,MovementReason,gen_id
from sqlalchemy.exc import IntegrityError
import re
from datetime import datetime

VALID_UNITS = {"kg", "g", "litre", "ml", "packet", "dozen", "piece"}
VALID_GST_SLABS = {0, 5, 12, 18, 28}

HSN_SUGGESTIONS = {
    ("atta", 0): "1101",
    ("atta", 5): "1101",
    ("salt", 5): "2501",
    ("butter", 12): "0405",
    ("sunflower oil", 5): "1512",
    ("maggi", 18): "1902",
    ("parle-g", 18): "1905",
    ("surf excel", 18): "3402",
    ("rice", 0): "1006",
    ("dal", 0): "0713",
}

STAPLE_KEYWORDS = {
    "atta", "wheat", "rice", "chawal", "dal", "besan", "suji", "rava", "poha",
    "jowar", "bajra", "maida", "salt", "namak",
}

 
def _check_gst_slab_plausible(name: str, is_loose: bool, gst_slab: float) -> str | None:
    """SOFT guardrail for the one remaining ambiguous direction: a packaged/
    branded staple marked GST-exempt (0%). This is a nudge, not an authoritative
    ruling — real GST-exempt packaged items exist depending on notification, so
    the owner can confirm past it with force=True. The other direction (loose
    item with nonzero GST) is no longer a warning — see the hard override in
    create_product/update_product below: loose items are always forced to 0%,
    since that's this store's policy, not a judgment call."""
    if is_loose:
        return None  # handled by the hard override, not this check
    name_lower = name.lower()
    if not any(keyword in name_lower for keyword in STAPLE_KEYWORDS):
        return None
    if gst_slab == 0:
        return (
            f"'{name}' is marked packaged/branded with GST 0% — packaged, branded "
            f"staples are usually taxed (commonly 5%) even when the loose version "
            f"of the same item is exempt. Confirm this is intentional."
        )
    return None

def _sku_slug(name: str) -> str:
    """Generate a readable SKU from a product name, e.g. 'Amul Butter 100g' -> 'AMUL-BUTTER-100G'."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip()).strip("-").upper()
    return slug[:40]


def _find_product(db, sku_or_name: str) -> Product | None:
    return db.query(Product).filter(
        (Product.sku == sku_or_name) | (Product.name.ilike(f"%{sku_or_name}%"))
    ).first()


@tool
def suggest_hsn(product_name: str, gst_slab: float) -> str:
    """Suggest a likely HSN code for a product based on its name and GST slab,
    using common kirana product categories. This is a SUGGESTION ONLY — always
    show it to the owner and get explicit confirmation before using it in
    create_product. Never treat this as authoritative or pass it to create_product
    without the owner confirming. If there's no match, say so and ask the owner
    to check their supplier invoice for the correct HSN code."""
    name_lower = product_name.lower()
    for (keyword, slab), hsn in HSN_SUGGESTIONS.items():
        if keyword in name_lower and slab == gst_slab:
            return f"Likely HSN code for '{product_name}': {hsn} (based on GST {gst_slab}%) — please confirm this is correct before I add it."
    return f"No HSN suggestion available for '{product_name}'. Please provide the HSN code from your supplier invoice, or I can proceed without full compliance detail if you're not sure."

@tool
def create_product(
    name: str,
    unit: str,
    is_loose: bool,
    cost_price: float,
    sell_price: float,
    hsn_code: str,
    gst_slab: float,
    reorder_level: float,
    initial_qty: float = 0,
    force: bool = False,
) -> str:
    """Add a BRAND NEW product to the catalog that has never existed before.
    Do NOT use this to add stock of an existing product — use receive_stock for that.
    If you're unsure whether the product already exists, call search_products first.
    Do NOT call this tool if GST slab or unit is missing from the owner's
    message — ask the owner for the missing detail instead of guessing a default.
    If the owner gives a GST rate but no HSN code, call suggest_hsn first and get
    their confirmation before calling this tool — do not guess an HSN code yourself.
    The SKU is generated automatically from the product name."""
    db = SessionLocal()
    try:
        unit = unit.strip().lower()
        if unit not in VALID_UNITS:
            return f"Invalid unit '{unit}'. Must be one of: {', '.join(sorted(VALID_UNITS))}"

        if gst_slab not in VALID_GST_SLABS:
            return f"Invalid GST slab {gst_slab}%. Must be one of: {sorted(VALID_GST_SLABS)}"
        
        gst_warning = _check_gst_slab_plausible(name, is_loose, gst_slab)
        if gst_warning and not force:
            return gst_warning + " Call again with force=True to confirm."
        
        if cost_price <= 0 or sell_price <= 0:
            return "Cost price and sell price must both be greater than zero"

        if sell_price < cost_price:
            return f"Warning: sell price (₹{sell_price}) is below cost price (₹{cost_price}) — confirm this is intentional before I proceed"

        sku = _sku_slug(name)
        existing = db.query(Product).filter(Product.sku == sku).first()
        if existing:
            unit_norm = unit.strip().lower()
            fields_match = (
                existing.name == name
                and existing.unit == unit_norm
                and existing.is_loose == (1 if is_loose else 0)
                and float(existing.cost_price) == float(cost_price)
                and float(existing.sell_price) == float(sell_price)
                and existing.hsn_code == hsn_code
                and float(existing.gst_slab) == float(gst_slab)
                and float(existing.reorder_level) == float(reorder_level)
            )
            if fields_match:
                return f"'{existing.name}' (SKU: {sku}) already exists with identical details — nothing to do."
            else:
                return (
                    f"A product with SKU '{sku}' already exists but with different details: "
                    f"existing = {existing.name}, ₹{existing.cost_price}/₹{existing.sell_price}, "
                    f"GST {existing.gst_slab}%, HSN {existing.hsn_code}. "
                    f"You're trying to add: {name}, ₹{cost_price}/₹{sell_price}, GST {gst_slab}%, HSN {hsn_code}. "
                    f"Use update_product if you meant to change it, or use a different SKU."
                )
        
        product = Product(
            id=gen_id(),
            sku=sku,
            name=name,
            unit=unit,
            is_loose=1 if is_loose else 0,
            cost_price=cost_price,
            sell_price=sell_price,
            hsn_code=hsn_code,
            gst_slab=gst_slab,
            qty_on_hand=initial_qty,
            reorder_level=reorder_level,
        )
        db.add(product)
        db.commit()
        return f"Created product '{product.name}' (SKU: {product.sku}), MRP ₹{product.sell_price}, GST {product.gst_slab}%, stock: {product.qty_on_hand} {product.unit}"

    except IntegrityError:
        db.rollback()
        return "A product with this SKU already exists (constraint violation)"
    finally:
        db.close()

@tool
def get_stock_level(sku_or_name: str) -> str:
    """Look up the current stock quantity for a product by SKU or name.
    Use this whenever the owner asks how much of an item is left."""
    db = SessionLocal()
    try:
        product = _find_product(db, sku_or_name)
        if not product:
            return f"No product found matching '{sku_or_name}'"
        return f"{product.name}: {product.qty_on_hand} {product.unit} in stock"
    finally:
        db.close()


@tool
def get_product(sku_or_name: str) -> str:
    """Look up full details for a single product — price, GST slab, HSN code, and current stock.
    Use this when the owner asks about a specific product's price, tax slab, or details.
    If the name might match multiple products, use search_products instead."""
    db = SessionLocal()
    try:
        product = _find_product(db, sku_or_name)
        if not product:
            return f"No product found matching '{sku_or_name}'"
        return (
            f"{product.name} (SKU: {product.sku})\n"
            f"Unit: {product.unit} | Loose: {'yes' if product.is_loose else 'no'}\n"
            f"Cost: ₹{product.cost_price} | MRP: ₹{product.sell_price}\n"
            f"GST: {product.gst_slab}% | HSN: {product.hsn_code}\n"
            f"Stock: {product.qty_on_hand} {product.unit} (reorder at {product.reorder_level})"
        )
    finally:
        db.close()


@tool
def search_products(query: str) -> str:
    """Search for products by partial name match. Returns all matches with SKU and key details.
    Use this when a product name is ambiguous or could refer to multiple products
    (e.g. 'atta' might match 'Aashirvaad Atta 5kg' and 'loose atta') — call this
    BEFORE create_product or add_bill_item if you're unsure which product the owner means,
    then ask the owner to pick if more than one match comes back."""
    db = SessionLocal()
    try:
        matches = db.query(Product).filter(Product.name.ilike(f"%{query}%")).limit(10).all()
        if not matches:
            return f"No products found matching '{query}'"
        lines = [
            f"- {p.name} (SKU: {p.sku}), {p.unit}, MRP ₹{p.sell_price}, stock: {p.qty_on_hand}"
            for p in matches
        ]
        return f"Found {len(matches)} match(es) for '{query}':\n" + "\n".join(lines)
    finally:
        db.close()



@tool
def update_product(
    sku: str,
    name: str | None = None,
    unit: str | None = None,
    cost_price: float | None = None,
    mrp: float | None = None,
    gst_slab: float | None = None,
    hsn_code: str | None = None,
    reorder_level: float | None = None,
    is_loose: bool | None = None,
    force: bool = False,
) -> str:
    """Edit fields on an EXISTING product identified by SKU — e.g. change its price,
    GST slab, or reorder level. Only pass the fields that are actually changing;
    leave others unset. Use get_product or search_products first to confirm the SKU
    if the owner referred to the product by name only."""
    db = SessionLocal()
    try:
        product = db.query(Product).filter(Product.sku == sku).first()
        if not product:
            return f"No product found with SKU '{sku}'"

        if unit is not None:
            unit_norm = unit.strip().lower()
            if unit_norm not in VALID_UNITS:
                return f"Invalid unit '{unit}'. Must be one of: {', '.join(sorted(VALID_UNITS))}"
            product.unit = unit_norm

        if gst_slab is not None:
            if gst_slab not in VALID_GST_SLABS:
                return f"Invalid GST slab {gst_slab}%. Must be one of: {sorted(VALID_GST_SLABS)}"
            product.gst_slab = gst_slab

        resulting_name = name if name is not None else product.name
        resulting_is_loose = is_loose if is_loose is not None else bool(product.is_loose)
        resulting_gst_slab = gst_slab if gst_slab is not None else float(product.gst_slab)
        gst_warning = _check_gst_slab_plausible(resulting_name, resulting_is_loose, resulting_gst_slab)
        if gst_warning and not force:
            return gst_warning + " Call again with force=True to confirm."

        if gst_slab is not None:
            product.gst_slab = gst_slab
        if is_loose is not None:
            product.is_loose = 1 if is_loose else 0

        if cost_price is not None:
            if cost_price <= 0:
                return "Cost price must be greater than zero"
            product.cost_price = cost_price

        if mrp is not None:
            if mrp <= 0:
                return "MRP must be greater than zero"
            product.sell_price = mrp

        # cross-check cost vs sell after any updates
        if float(product.sell_price) < float(product.cost_price):
            db.rollback()
            return f"Update rejected: resulting MRP (₹{product.sell_price}) would be below cost price (₹{product.cost_price})"

        if name is not None:
            product.name = name
        if hsn_code is not None:
            product.hsn_code = hsn_code
        if reorder_level is not None:
            product.reorder_level = reorder_level

        db.commit()
        return f"Updated '{product.name}' (SKU: {product.sku}): cost ₹{product.cost_price}, MRP ₹{product.sell_price}, GST {product.gst_slab}%"
    finally:
        db.close()


@tool
def receive_stock(
    sku_or_name: str,
    qty: float,
    cost_price: float | None = None,
    mrp: float | None = None,
) -> str:
    """Record newly received stock for a product that ALREADY EXISTS in the catalog
    (e.g. "50 packets of Maggi came in, cost ₹12, MRP ₹14"). Do NOT use this to add a
    product that doesn't exist yet — use create_product for that. Optionally updates
    cost price and/or MRP if the owner mentions new prices with this delivery."""
    db = SessionLocal()
    try:
        if qty <= 0:
            return "Quantity received must be greater than zero"

        product = _find_product(db, sku_or_name)
        if not product:
            return f"No product found matching '{sku_or_name}'. Use create_product if this is a new item."

        product.qty_on_hand = float(product.qty_on_hand) + qty
        if cost_price is not None:
            product.cost_price = cost_price
        if mrp is not None:
            product.sell_price = mrp

        movement = StockMovement(
            id=gen_id(),
            product_id=product.id,
            delta=qty,
            reason=MovementReason.receive,
            ref_id=None,
            created_at=datetime.utcnow(),
        )
        db.add(movement)
        db.commit()

        return f"Received {qty} {product.unit} of {product.name}. New stock: {product.qty_on_hand} {product.unit}"
    finally:
        db.close()





@tool
def list_low_stock() -> str:
    """List all products at or below their reorder level. Use this when the owner
    asks what's running out, what needs reordering, or for a stock health check."""
    db = SessionLocal()
    try:
        low = db.query(Product).filter(Product.qty_on_hand <= Product.reorder_level).all()
        if not low:
            return "Nothing is currently low on stock."
        lines = [
            f"- {p.name}: {p.qty_on_hand} {p.unit} left (reorder at {p.reorder_level})"
            for p in low
        ]
        return f"{len(low)} item(s) at or below reorder level:\n" + "\n".join(lines)
    finally:
        db.close()