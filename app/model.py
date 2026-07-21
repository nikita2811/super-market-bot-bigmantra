import uuid
import enum
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Numeric, DateTime, ForeignKey, Enum, UniqueConstraint, Text,Float,Date
)
from sqlalchemy.orm import relationship


from sqlalchemy.orm import declarative_base

Base = declarative_base()

def gen_id():
    return str(uuid.uuid4())


class BillStatus(str, enum.Enum):
    draft = "draft"
    finalized = "finalized"
    cancel = "cancel"


class MovementReason(str, enum.Enum):
    receive = "receive"
    sale = "sale"
    adjustment = "adjustment"


class AccountType(str, enum.Enum):
    credit_sale = "credit_sale"
    payment = "payment"


class Product(Base):
    __tablename__ = "products"
    id = Column(String, primary_key=True, default=gen_id,index=True)
    sku = Column(String, unique=True, nullable=False)          
    name = Column(String, nullable=False)                      
    unit = Column(String, nullable=False)                      
    is_loose = Column(Integer, default=0)                       
    cost_price = Column(Numeric(10, 2), nullable=False)
    sell_price = Column(Numeric(10, 2), nullable=False)         
    hsn_code = Column(String, nullable=False)
    gst_slab = Column(Numeric(4, 2), nullable=False)            
    qty_on_hand = Column(Numeric(12, 3), nullable=False, default=0)
    reorder_level = Column(Numeric(12, 3), nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class StockMovement(Base):
    __tablename__ = "stock_movements"
    id = Column(String, primary_key=True, default=gen_id)
    product_id = Column(String, ForeignKey("products.id"), nullable=False)
    delta = Column(Numeric(12, 3), nullable=False)               # signed
    reason = Column(Enum(MovementReason), nullable=False)
    ref_id = Column(String, nullable=True)                       # bill id, etc.
    created_at = Column(DateTime, default=datetime.utcnow)


class Customer(Base):
    __tablename__ = "customers"
    id = Column(String, primary_key=True, default=gen_id)
    name = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    account_balance = Column(Numeric(10, 2), nullable=False, default=0)
    chat_id= Column(String,nullable=True)  # cached rollup


class AccountTransaction(Base):
    __tablename__ = "account_transactions"
    id = Column(String, primary_key=True, default=gen_id)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False)
    type = Column(Enum(AccountType), nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)              # always positive
    ref_bill_id = Column(String, nullable=True)
    idempotency_key = Column(String, unique=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Bill(Base):
    __tablename__ = "bills"
    id = Column(String, primary_key=True, default=gen_id)
    chat_id = Column(String, nullable=False)
    status = Column(Enum(BillStatus), nullable=False, default=BillStatus.draft)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=True)
    payment_mode = Column(String, nullable=True)                 
    payment_ref = Column(String, nullable=True)
    subtotal = Column(Numeric(10, 2), nullable=False, default=0)
    cgst = Column(Numeric(10, 2), nullable=False, default=0)
    sgst = Column(Numeric(10, 2), nullable=False, default=0)
    total = Column(Numeric(10, 2), nullable=False, default=0)
    idempotency_key = Column(String, unique=True, nullable=True)  # enforced at finalize
    created_at = Column(DateTime, default=datetime.utcnow)
    finalized_at = Column(DateTime, nullable=True)

    items = relationship("BillItem", backref="bill", cascade="all, delete-orphan")


class BillItem(Base):
    __tablename__ = "bill_items"
    id = Column(String, primary_key=True, default=gen_id)
    bill_id = Column(String, ForeignKey("bills.id"), nullable=False)
    product_id = Column(String, ForeignKey("products.id"), nullable=False)
    product_name = Column(String, nullable=False)                # denormalized for invoice stability
    qty = Column(Numeric(12, 3), nullable=False)
    unit_price = Column(Numeric(10, 2), nullable=False)
    gst_slab = Column(Numeric(4, 2), nullable=False)
    hsn_code = Column(String, nullable=False)
    line_subtotal = Column(Numeric(10, 2), nullable=False)
    cgst_amt = Column(Numeric(10, 2), nullable=False)
    sgst_amt = Column(Numeric(10, 2), nullable=False)
    line_total = Column(Numeric(10, 2), nullable=False)


class Preference(Base):
    __tablename__ = "preferences"
    id = Column(String, primary_key=True, default=gen_id)
    owner_id = Column(String, nullable=False, default="default")
    key = Column(String, nullable=False)
    value = Column(Text, nullable=False)
    shop_name= Column(String,nullable=True)
    address=Column(String,nullable=True)
    gstin=Column(String,nullable=True)
    phone=Column(Integer,nullable=True)
    __table_args__ = (UniqueConstraint("owner_id", "key", name="uq_owner_key"),)


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    chat_id = Column(String, primary_key=True)
    owner_id = Column(String, nullable=False, default="default")
    current_draft_bill_id = Column(String, nullable=True)


class ProcessedUpdate(Base):
    __tablename__ = "processed_updates"
    update_id = Column(String, primary_key=True)
    processed_at = Column(DateTime, default=datetime.utcnow)





class DailyClosure(Base):
    __tablename__ = "daily_closures"

    id = Column(String, primary_key=True, default=gen_id)
    closure_date = Column(Date, unique=True, nullable=False)
    total_sales = Column(Float, nullable=False)
    total_tax = Column(Float, nullable=False)
    cash_total = Column(Float, default=0)
    upi_total = Column(Float, default=0)
    card_total = Column(Float, default=0)
    other_total = Column(Float, default=0)
    bill_count = Column(Integer, default=0)
    top_items_json = Column(Text)
    closed_at = Column(DateTime, nullable=False)



