from deepagents import create_deep_agent
from app.tools.product_tools import (create_product, get_stock_level,update_product,
                                     get_product,search_products,receive_stock,list_low_stock)
from app.tools.credit_leadger_tools import (get_or_create_customer,add_credit,record_payment,get_balance)
from app.tools.preferences_tools import (get_preference,set_preference,get_shop_details,set_shop_details)
from app.tools.billing_tools import (start_bill,add_bill_item,remove_bill_item,get_bill_draft,finalize_bill,cancel_bill,update_bill_item)
from app.tools.analytics_tools import (get_daily_summary,close_day,get_sales_range)
from app.tools.invoice_tools import (generate_invoice_pdf)
from app.tools.analytics_document import (generate_report_pptx)
import os
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool

DATABASE_URL = os.getenv("DATABASE_URL")



def init_checkpointer():
    """Returns a connection pool wrapped as a context manager, safe for concurrent requests."""
    pool = ConnectionPool(
        conninfo=DATABASE_URL,
        max_size=20,
        kwargs={"autocommit": True, "prepare_threshold": None},
    )
    return pool


def build_agent(pool):
    checkpointer = PostgresSaver(pool)
    return create_deep_agent(
        model=os.getenv("AGENT_MODEL"),
        tools=[create_product, get_stock_level,update_product,get_product,search_products,receive_stock,list_low_stock,get_or_create_customer,add_credit,record_payment,get_balance
               ,get_preference,set_preference,set_shop_details,get_shop_details,start_bill,add_bill_item,remove_bill_item,get_bill_draft,finalize_bill,cancel_bill,update_bill_item
               ,get_daily_summary,close_day,get_sales_range
               ,generate_invoice_pdf
               ,generate_report_pptx],
        system_prompt=(
            "You run a super market store's operations via chat. The owner writes in "
    "short, terse, real-shopkeeper English or Hinglish or Hindi — messages may be fragments, "
    "missing punctuation, or mix Hindi words. Parse the intent even from casual phrasing. "
    "Always use tools for prices, stock, and GST — never invent numbers. "
    "Ask a clarifying question when a product name is ambiguous or a required detail is missing."
        ),
    checkpointer=checkpointer,
    )