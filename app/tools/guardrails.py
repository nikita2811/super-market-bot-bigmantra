from dataclasses import dataclass
from app.model import Customer


@dataclass
class GuardrailResult:
    allowed: bool
    needs_confirmation: bool
    message: str | None = None





def check_not_below_cost(product, unit_price: float, force: bool = False) -> GuardrailResult:
    """Refuse (with a path to confirm) if the sale price is below the product's
    recorded cost price.
    """
    cost_price = getattr(product, "cost_price", None)
    if cost_price is None:
        return GuardrailResult(allowed=True, needs_confirmation=False)

    cost_price = float(cost_price)
    unit_price = float(unit_price)

    if unit_price < cost_price:
        if force:
            return GuardrailResult(allowed=True, needs_confirmation=False)
            
        loss_per_unit = cost_price - unit_price
        return GuardrailResult(allowed=False, needs_confirmation=True, message=
            f"Selling {product.name} at ₹{unit_price} is below cost (₹{cost_price}) — "
            f"a loss of ₹{loss_per_unit:.2f} per unit. If this is intentional "
            f"(clearance, damaged stock, owner override), confirm by calling again "
            f"with force=True."
        )
    return GuardrailResult(allowed=True, needs_confirmation=False)




def check_stock_change_is_legitimate(reason, delta: float, current_qty_on_hand: float) -> GuardrailResult:
    """Refuse any stock change that isn't an enumerated, audited reason, and refuse
    any change that would push stock negative or that erases history rather than
    recording a movement.
    """
    from app.model import MovementReason  # adjust import path if it differs

    if reason not in (MovementReason.sale, MovementReason.adjustment):
        return GuardrailResult(allowed=False, needs_confirmation=False, message=
            f"'{reason}' is not a permitted stock movement reason. Stock can only "
            f"be changed via a sale or a logged adjustment — never deleted or "
            f"reset outside the audit trail."
        )

    resulting_qty = float(current_qty_on_hand) + float(delta)
    if resulting_qty < 0:
        return GuardrailResult(allowed=False, needs_confirmation=False, message=
            f"This change would take stock to {resulting_qty}, which is invalid — "
            f"stock can't go negative."
        )
    return GuardrailResult(allowed=True, needs_confirmation=False)
    




def check_account_settlement_is_valid(db, customer_id: str, amount: float) -> GuardrailResult:
    """Refuse settling a khata (credit account) if the customer doesn't exist, has
    no outstanding balance, or the settlement amount exceeds what's actually owed.
    """
      

    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        return GuardrailResult(allowed=False, needs_confirmation=False, message=
            f"No customer found for id '{customer_id}' — can't settle a khata that doesn't exist."
        )

    outstanding = float(getattr(customer, "account_balance", 0) or 0)
    name = getattr(customer, "name", customer_id)

    if outstanding <= 0:
        return GuardrailResult(allowed=False, needs_confirmation=False, message=
            f"{name} has no outstanding khata balance — there's nothing to settle."
        )

    if float(amount) > outstanding:
        return GuardrailResult(allowed=False, needs_confirmation=False, message=
            f"Settlement amount ₹{amount} exceeds {name}'s outstanding khata balance "
            f"of ₹{outstanding} — can't settle more than what's owed."
        )
    return GuardrailResult(allowed=True, needs_confirmation=False)

def check_oversell(product,qty_on_hand:float, already_reserved: float = 0)->GuardrailResult:
    """Hard refuse if qty_requested (plus whatever's already reserved on this
    draft bill for the same product) exceeds current stock. No force flag —
    overselling has no legitimate override; if stock is genuinely wrong, fix it
    via adjust_stock first, then retry the sale."""
    available = float(product.qty_on_hand) - float(already_reserved)
    if qty_on_hand > available:
        return GuardrailResult(allowed=False, needs_confirmation=False, message=
            f"Not enough stock: only {available} {product.unit} of {product.name} "
            f"available (have {product.qty_on_hand}, {already_reserved} already reserved) — "
            f"can't add {qty_on_hand}."
        )
    return GuardrailResult(allowed=True, needs_confirmation=False)