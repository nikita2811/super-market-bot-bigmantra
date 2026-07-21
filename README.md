# Supermarket bot

Run an Indian kirana / supermarket store end-to-end from a Telegram chat — receiving stock, cutting GST-correct bills, running customer khata (credit), closing the day, and generating invoices and analysis decks on demand.

**Telegram bot:** `@Nikita@2811Bot`(Super Market handler)

---

## 1. Harness — why `deepagents`

The agent is built on [`deepagents`] (`app/agent.py`), on top of LangGraph.

Reasons for this choice over a hand-rolled loop or a plain Vercel-AI-SDK agent:

- It gives a proper **observe → reason → act → feed-result-back → continue** loop for free, including chaining multiple tool calls in a single turn (e.g. `search_products` → `add_bill_item` → `add_bill_item` → `get_bill_draft` in one owner message).
- It runs on LangGraph, which ships a first-class **Postgres checkpointer** (`PostgresSaver`). That's what backs both conversation-level memory (mid-bill edits, "drop the butter, make it 6 Maggi") and, combined with our own `Preference` table, durable memory that survives a new chat.
- No intent router. There is no regex/keyword layer anywhere in this codebase — every decision about *which* tool to call, in what order, and whether to ask a clarifying question is made by the model, driven purely by tool descriptions and the system prompt in `build_agent()`.

## 2. Architecture

```
Telegram ──▶ FastAPI webhook (main.py)
               │
               ├─ dedupe update_id (ProcessedUpdate table)
               ├─ ensure chat_sessions row exists
               ├─ text message ──────────────────┐
               └─ voice note ─▶ Gemini transcribe ┘
                                                    │
                                          handle_telegram_message (bot.py)
                                                    │
                                    deepagents agent, thread_id = chat_id
                                    (Postgres-checkpointed conversation state)(agent.py)
                                                    │
                        ┌───────────────┬───────────────┬────────────────┬──────────────┐
                   product_tools   billing_tools   credit_leadger    analytics_tools  invoice_tools /
                   (catalog/stock) (bills, GST,      _tools (khata)   / _document      analytics_document
                                    oversell guard)                   (summaries,      (PDF / PPTX)
                                                                        decks)
                                                    │
                                              Postgres (SQLAlchemy models, app/model.py)
                                              Alembic-managed schema
```

Everything the owner can trigger — receiving stock, billing, khata, closing the day, invoices, decks, preferences — is a plain Python function decorated with `@tool` and registered in `build_agent()`. There is no admin UI or CRUD layer; the tool surface *is* the product.

## 3. Control loop

1. Telegram delivers an update to the webhook. The `update_id` is recorded so a redelivered update is a no-op.
2. The message (or transcribed voice note) is handed to the agent as a single user turn, with `chat_id` used as both the LangGraph `thread_id` (for mid-conversation state, e.g. an in-progress bill) and passed into tool `config` where a tool needs to know which chat it's serving (e.g. `start_bill`).
3. The model reasons over the message, calls whatever tools it needs — possibly several in sequence — and the results are fed back into its context before it produces a final reply.
4. If a tool produced a file (`generate_invoice_pdf`, `generate_report_pptx`), the tool's return value embeds a `FILE_PATH:` marker; `bot.py` extracts it and `main.py` sends the file via `sendDocument` alongside the reply text.

## 4. Tool / skill surface

| File | Tools | Responsibility |
|---|---|---|
| `product_tools.py` | `create_product`, `update_product`, `receive_stock`, `get_stock_level`, `get_product`, `search_products`, `list_low_stock`, `suggest_hsn` | Catalog, stock levels, HSN/GST metadata |
| `billing_tools.py` | `start_bill`, `add_bill_item`, `update_bill_item`, `remove_bill_item`, `get_bill_draft`, `finalize_bill`, `cancel_bill` | Draft bills, GST math, oversell guard, atomic stock decrement, idempotent finalize |
| `credit_leadger_tools.py` | `get_or_create_customer`, `add_credit`, `record_payment`, `get_balance` | Khata (credit ledger) |
| `analytics_tools.py` | `get_daily_summary`, `close_day`, `get_sales_range` | Daily/range sales summaries, locking a day's numbers |
| `invoice_tools.py` | `generate_invoice_pdf` | GST tax invoice as PDF (`invoice_template.py`) |
| `analytics_document.py` | `generate_report_pptx` | Sales analysis deck with real charts (`chart_utils.py`) |
| `preferences_tools.py` | `get_preference`, `set_preference`, `get_shop_details`, `set_shop_details` | Standing owner preferences and shop/GSTIN details, persisted outside the conversation |
| `guardrails.py` | (not tools — shared helpers) | `check_oversell`, `check_not_below_cost`, `check_khata_settlement_is_valid`, `check_stock_change_is_legitimate` |

Tools are deliberately thin and single-purpose; composition (e.g. "look the product up, then decide whether to `add_bill_item` or ask a clarifying question") is wired to the model, not hardcoded.

## 5. How each "hard part" is handled

- **Grounding.** Every price, GST slab, and stock figure the model states comes from a tool call against `Product`/`Bill` rows — the system prompt explicitly forbids inventing numbers, and there is no path for the model to fabricate a price or stock level since replies are built from tool return strings.
- **Oversell guard.** `check_oversell()` in `guardrails.py` is enforced inside `add_bill_item` / `update_bill_item` at the tool layer, against a `SELECT ... FOR UPDATE`-locked product row — not a prompt instruction.
- **GST correctness.** `calculate_gst()` in `billing_tools.py` computes tax per the item's own slab, splits it into CGST/SGST for intra-state sales, and rounds with `ROUND_HALF_UP` at 2 decimal places using `Decimal` throughout to avoid float drift. The invoice PDF renders the full per-line tax breakup plus amount-in-words.
- **Multi-turn bills.** `start_bill` opens a draft; `add_bill_item` / `update_bill_item` / `remove_bill_item` mutate it across as many messages as needed; stock is only decremented once, in `finalize_bill`.
- **Idempotency.** `finalize_bill` takes an `idempotency_key`, checked against a unique DB column before any stock mutation happens, and the bill row itself is locked (`with_for_update`) for the duration of finalize so a concurrent retry blocks until the first attempt commits, then sees the bill already finalized.
- **Concurrency.** Row-level locks (`with_for_update()`) on the product being sold protect `add_bill_item`, `update_bill_item`, and `finalize_bill` against a sale and a stock-in racing each other on the same SKU.
- **Guardrails.** `check_not_below_cost` refuses (with a `force=True` override) selling under cost; oversell has no override; khata settlement is checked against the customer's actual balance before a payment is recorded.
- **Real artifacts.** The PDF invoice (`reportlab`) and PPTX deck (`python-pptx` + `matplotlib`) are generated programmatically from live data.
- **Memory across sessions.** Standing preferences (default payment mode, preferred brand, shop name/GSTIN) live in a `Preference` table keyed by `owner_id` along with shop details, entirely separate from the LangGraph conversation thread — so they're available to a fresh `/new` chat, not just recalled from message history.

## 6. Running it locally

```bash
cp .env.example .env   # fill in TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET,
                        # ANTHROPIC_API_KEY / AGENT_MODEL, GEMINI_API_KEY, DATABASE_URL

docker compose up --build
docker compose exec bot alembic upgrade head
```

Then point your Telegram bot's webhook at `https://<your-host>/webhook/<TELEGRAM_BOT_TOKEN>`.
.

## 7. Scenarios covered in the demo recording

1. Receive stock for an existing SKU.
2. Multi-item bill with a mid-build edit ("drop the butter, make it 6 Maggi").
3. Oversell guard refusing a bill that exceeds stock.
4. A full khata cycle: credit a customer, check balance, record a payment.
5. Generate a PDF invoice for a finalized bill.
6. Generate a sales analysis deck (PPTX) for a date range.
7. Set a standing preference, start a `/new` chat, and show it's still remembered.

## Important Note : 
1. I deployed the bot agent on Render free instance so bot might take some time to reply back