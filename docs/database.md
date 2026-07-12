# Database Schema Reference

The engine uses SQLite stored at `data/workflow.db`. The database is created and seeded automatically when the FastAPI backend starts.

## Initialization

The database is automatically created and seeded when the FastAPI backend starts (via the lifespan handler in `main.py`). You can also manage it standalone:

```bash
# Initialize and seed (idempotent — safe to run repeatedly)
python -m workflow_engine.database

# Reset: delete existing DB and recreate from scratch
python -m workflow_engine.database --reset
```

Use `--reset` after schema changes (e.g., adding columns) to recreate the database with the updated schema and fresh seed data.

## Connection

All database access is async via `aiosqlite`. Helper functions are in `workflow_engine/database/db.py`:

```python
from workflow_engine.database.db import query_one, query_all, execute

# Fetch one row as a dict (or None)
customer = await query_one("SELECT * FROM customers WHERE customer_id = ?", ("CUST-456",))

# Fetch all rows as list of dicts
orders = await query_all("SELECT * FROM orders WHERE customer_id = ?", ("CUST-456",))

# Insert/update, returns lastrowid
await execute("INSERT INTO cases (case_id, status, created_at) VALUES (?, ?, ?)", (...))
```

## Tables

### customers

Customer profiles.

| Column | Type | Description |
|--------|------|-------------|
| `customer_id` | TEXT PK | e.g., `CUST-456` |
| `name` | TEXT | Full name |
| `email` | TEXT | Email address |
| `phone` | TEXT | Phone number |
| `account_status` | TEXT | `active`, `suspended`, etc. |
| `loyalty_tier` | TEXT | `bronze`, `silver`, `gold` |
| `total_orders` | INTEGER | Lifetime order count |
| `member_since` | TEXT | ISO date |

### orders

Customer orders.

| Column | Type | Description |
|--------|------|-------------|
| `order_id` | TEXT PK | e.g., `ORD-123` |
| `customer_id` | TEXT FK | References `customers` |
| `merchant_name` | TEXT | Store/merchant name (e.g., `TechMart Electronics`) |
| `total` | REAL | Order total |
| `status` | TEXT | `processing`, `shipped`, `delivered` |
| `order_date` | TEXT | ISO date |
| `delivery_date` | TEXT | ISO date or NULL |
| `days_since_delivery` | INTEGER | Computed at seed time |
| `payment_method` | TEXT | e.g., `credit_card_ending_4242` |
| `shipping_address` | TEXT | Full address |

### order_items

Line items within an order.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `order_id` | TEXT FK | References `orders` |
| `name` | TEXT | Item name |
| `sku` | TEXT | SKU code |
| `qty` | INTEGER | Quantity |
| `price` | REAL | Unit price |

### accounts

Accounts for the fraud operations domain (separate from customers).

| Column | Type | Description |
|--------|------|-------------|
| `account_id` | TEXT PK | e.g., `ACCT-1001` |
| `customer_name` | TEXT | Account holder name |
| `email` | TEXT | Email address |
| `status` | TEXT | `active`, `freeze`, `restrict`, `monitor` |

### transactions

Financial transactions linked to accounts.

| Column | Type | Description |
|--------|------|-------------|
| `txn_id` | TEXT PK | e.g., `TXN-5001` |
| `account_id` | TEXT FK | References `accounts` |
| `amount` | REAL | Transaction amount |
| `merchant` | TEXT | Merchant name |
| `date` | TEXT | ISO datetime |
| `location` | TEXT | Geographic location |
| `is_flagged` | INTEGER | `0` or `1` |
| `type` | TEXT | `purchase`, `subscription` |

### fraud_alerts

Fraud monitoring alerts.

| Column | Type | Description |
|--------|------|-------------|
| `alert_id` | TEXT PK | e.g., `FA-001` |
| `type` | TEXT | `card_not_present`, `account_takeover`, `unusual_activity` |
| `severity` | TEXT | `low`, `medium`, `high` |
| `risk_score` | INTEGER | 0-100 |
| `account_id` | TEXT FK | References `accounts` |
| `customer_name` | TEXT | Account holder |
| `triggered_at` | TEXT | ISO datetime |
| `description` | TEXT | Alert description |
| `amount_involved` | REAL | Monetary amount |
| `transactions_flagged` | INTEGER | Count of flagged transactions |
| `status` | TEXT | `open`, `closed` |

### devices

Known devices associated with accounts.

| Column | Type | Description |
|--------|------|-------------|
| `device_id` | TEXT PK | e.g., `DEV-001` |
| `account_id` | TEXT FK | References `accounts` |
| `type` | TEXT | Device model |
| `os` | TEXT | Operating system |
| `first_seen` | TEXT | ISO date |
| `trusted` | INTEGER | `0` or `1` |

### login_history

Login events for fraud analysis.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `account_id` | TEXT FK | References `accounts` |
| `device` | TEXT | Device description |
| `device_id` | TEXT | Device identifier |
| `location` | TEXT | Geographic location |
| `timestamp` | TEXT | ISO datetime |
| `is_new` | INTEGER | `0` or `1` — whether this is a new device |
| `ip` | TEXT | IP address |

### risk_indicators

Risk signals associated with an account.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `account_id` | TEXT FK | References `accounts` |
| `indicator` | TEXT | e.g., `new_device_login`, `geographic_anomaly` |

### cases

Support and fraud cases.

| Column | Type | Description |
|--------|------|-------------|
| `case_id` | TEXT PK | e.g., `CASE-001` or `FRAUD-20260221...` |
| `customer_id` | TEXT | Customer or account ID |
| `status` | TEXT | `open`, `resolved`, `closed`, `escalated`, `account_flagged` |
| `created_at` | TEXT | ISO datetime |
| `updated_at` | TEXT | ISO datetime |
| `notes` | TEXT | Summary notes |

### case_notes

Individual notes added to cases.

| Column | Type | Description |
|--------|------|-------------|
| `note_id` | TEXT PK | e.g., `NOTE-20260221...` |
| `case_id` | TEXT FK | References `cases` |
| `note` | TEXT | Note content |
| `created_at` | TEXT | ISO datetime |
| `created_by` | TEXT | `system` or agent identifier |

### escalations

Escalation records.

| Column | Type | Description |
|--------|------|-------------|
| `escalation_id` | TEXT PK | e.g., `ESC-20260221...` |
| `case_id` | TEXT | Associated case |
| `reason` | TEXT | Escalation reason |
| `priority` | TEXT | `low`, `medium`, `high`, `urgent` |
| `assigned_to` | TEXT | Supervisor name |
| `estimated_response` | TEXT | e.g., `within 2 hours` |
| `escalated_at` | TEXT | ISO datetime |
| `status` | TEXT | `escalated` |

### refunds

Processed refunds.

| Column | Type | Description |
|--------|------|-------------|
| `refund_id` | TEXT PK | e.g., `REF-123-143022` |
| `order_id` | TEXT FK | References `orders` |
| `amount` | REAL | Refund amount |
| `currency` | TEXT | `USD` |
| `status` | TEXT | `processed` |
| `reason` | TEXT | Refund reason |
| `refund_method` | TEXT | Payment method used |
| `estimated_days` | TEXT | e.g., `5-7 business days` |
| `processed_at` | TEXT | ISO datetime |

### knowledge_articles

Knowledge base articles for agent reference.

| Column | Type | Description |
|--------|------|-------------|
| `article_id` | TEXT PK | e.g., `KB-001` |
| `title` | TEXT | Article title |
| `summary` | TEXT | Article summary |
| `content` | TEXT | Full article content (nullable) |
| `relevance_score` | REAL | Default relevance ranking |

## Seed Data

The `seed_all()` function in `workflow_engine/database/seed.py` populates the database with:

- **4 customers** — Jane Smith, Bob Johnson, Alice Williams, Carol Davis
- **4 orders** — delivered (TechMart Electronics), shipped (SportZone), processing (GadgetWorld), and old-delivered (HomeOffice Supplies)
- **5 order items** — across the 4 orders
- **4 accounts** — Michael Chen, Sarah Parker, David Lee, Emily Brown
- **11 transactions** — mix of flagged and normal across 3 accounts
- **4 fraud alerts** — high/medium/low severity scenarios
- **5 devices** — trusted devices across 3 accounts
- **5 login history entries** — including new device logins
- **7 risk indicators** — for accounts 1001 and 2002
- **4 knowledge articles** — refund policy, escalation, fraud guidelines, store credit

Seeding is idempotent — running it multiple times will not create duplicates. Time-sensitive tables (orders, transactions, fraud_alerts, disputes) use `INSERT OR REPLACE` so that computed dates stay current on each restart. Static tables use `INSERT OR IGNORE` and count-based guards.

## Deterministic core tables

The SQLite `CoreStore` adapter creates these tables in `DATABASE_URL`:

| Table | Purpose |
|---|---|
| `workflow_cases` | Procedure/version lock, customer binding, status, optimistic version |
| `case_facts` | Typed value, authority, source, evidence, expiry and supersession |
| `action_attempts` | Unique idempotency key, typed command, lifecycle and connector outcome |
| `inbox_messages` | Provider-message dedupe and normalized chat/IVR envelope |
| `handoffs` | Requested/accepted/timed-out/failed/resolved transfer state |

`refunds.order_id` has a unique index. Startup migration retains the earliest
historical prototype refund per order before creating that index. The action
record remains the audit source for authorization and reconciliation.

### Database portability

Core logic targets the `CoreStore` protocol. `create_core_store()` supplies the
SQLite adapter by default and accepts URL-scheme adapter factories for other
databases. A production adapter must preserve transactions, optimistic compare-
and-swap, unique idempotency keys, inbox uniqueness, and durable handoff updates.

## ADK 2.x session database

ADK sessions are no longer stored in the domain database. They use
`ADK_SESSION_DATABASE_URL` (default `data/adk_sessions_v2.db`) because ADK 2.x has
an async SQLAlchemy schema that is incompatible with the historical 1.9 tables.
Never treat ADK events or state as the compliance/action authority.
