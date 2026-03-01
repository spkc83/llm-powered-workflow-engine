"""SQLite database connection, schema creation, and query helpers.

Provides connection pooling via a shared connection, configurable DB path
via settings, and structured logging for all database operations.
"""

from pathlib import Path
from typing import Optional

import aiosqlite

from ..logging_config import get_logger

logger = get_logger("database")

# Default path, overridden by settings at startup
DB_PATH: Path = Path("data/workflow.db")

# Connection pool (simple shared connection for SQLite; for PostgreSQL
# in production, replace with SQLAlchemy async engine + session pool)
_connection_pool: Optional[aiosqlite.Connection] = None

_SCHEMA = """
-- Customers
CREATE TABLE IF NOT EXISTS customers (
    customer_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT,
    account_status TEXT DEFAULT 'active',
    loyalty_tier TEXT DEFAULT 'bronze',
    total_orders INTEGER DEFAULT 0,
    member_since TEXT NOT NULL
);

-- Orders
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(customer_id),
    merchant_name TEXT NOT NULL,
    total REAL NOT NULL,
    status TEXT NOT NULL,
    order_date TEXT NOT NULL,
    delivery_date TEXT,
    days_since_delivery INTEGER DEFAULT 0,
    payment_method TEXT,
    shipping_address TEXT
);

-- Order Items
CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL REFERENCES orders(order_id),
    name TEXT NOT NULL,
    sku TEXT NOT NULL,
    qty INTEGER NOT NULL,
    price REAL NOT NULL
);

-- Accounts (for fraud domain)
CREATE TABLE IF NOT EXISTS accounts (
    account_id TEXT PRIMARY KEY,
    customer_name TEXT NOT NULL,
    email TEXT,
    status TEXT DEFAULT 'active'
);

-- Transactions
CREATE TABLE IF NOT EXISTS transactions (
    txn_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(account_id),
    amount REAL NOT NULL,
    merchant TEXT NOT NULL,
    date TEXT NOT NULL,
    location TEXT,
    is_flagged INTEGER DEFAULT 0,
    type TEXT DEFAULT 'purchase'
);

-- Fraud Alerts
CREATE TABLE IF NOT EXISTS fraud_alerts (
    alert_id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    severity TEXT NOT NULL,
    risk_score INTEGER NOT NULL,
    account_id TEXT NOT NULL REFERENCES accounts(account_id),
    customer_name TEXT NOT NULL,
    triggered_at TEXT NOT NULL,
    description TEXT,
    amount_involved REAL,
    transactions_flagged INTEGER,
    status TEXT DEFAULT 'open'
);

-- Devices
CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(account_id),
    type TEXT NOT NULL,
    os TEXT,
    first_seen TEXT,
    trusted INTEGER DEFAULT 0
);

-- Login History
CREATE TABLE IF NOT EXISTS login_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL REFERENCES accounts(account_id),
    device TEXT NOT NULL,
    device_id TEXT,
    location TEXT,
    timestamp TEXT NOT NULL,
    is_new INTEGER DEFAULT 0,
    ip TEXT
);

-- Risk Indicators
CREATE TABLE IF NOT EXISTS risk_indicators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL REFERENCES accounts(account_id),
    indicator TEXT NOT NULL
);

-- Cases
CREATE TABLE IF NOT EXISTS cases (
    case_id TEXT PRIMARY KEY,
    customer_id TEXT,
    status TEXT DEFAULT 'open',
    created_at TEXT NOT NULL,
    updated_at TEXT,
    notes TEXT
);

-- Case Notes
CREATE TABLE IF NOT EXISTS case_notes (
    note_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(case_id),
    note TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by TEXT DEFAULT 'system'
);

-- Escalations
CREATE TABLE IF NOT EXISTS escalations (
    escalation_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    priority TEXT NOT NULL,
    assigned_to TEXT,
    estimated_response TEXT,
    escalated_at TEXT NOT NULL,
    status TEXT DEFAULT 'escalated'
);

-- Refunds
CREATE TABLE IF NOT EXISTS refunds (
    refund_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(order_id),
    amount REAL NOT NULL,
    currency TEXT DEFAULT 'USD',
    status TEXT DEFAULT 'processed',
    reason TEXT,
    refund_method TEXT,
    estimated_days TEXT,
    processed_at TEXT NOT NULL
);

-- EFT Disputes (Reg E compliance)
CREATE TABLE IF NOT EXISTS disputes (
    dispute_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(customer_id),
    transaction_id TEXT NOT NULL,
    account_id TEXT,
    dispute_type TEXT NOT NULL,        -- unauthorized, error, fraud
    amount REAL NOT NULL,
    merchant TEXT NOT NULL,
    transaction_date TEXT NOT NULL,
    reported_date TEXT NOT NULL,
    statement_date TEXT,               -- date of statement showing the transaction
    days_since_transaction INTEGER,
    days_since_statement INTEGER,
    liability_tier TEXT,               -- tier_1 ($50), tier_2 ($500), tier_3 (unlimited)
    max_liability REAL,
    status TEXT DEFAULT 'open',        -- open, investigating, provisional_credit, resolved, denied
    provisional_credit_issued INTEGER DEFAULT 0,
    provisional_credit_date TEXT,
    provisional_credit_amount REAL,
    resolution TEXT,                   -- refunded, denied, partial
    resolution_date TEXT,
    resolution_reason TEXT,
    investigation_deadline TEXT,        -- 10 business days initial, 45/90 calendar days final
    payment_method TEXT,               -- debit_card, ach, wire, p2p
    metadata TEXT                      -- JSON for additional context
);

CREATE INDEX IF NOT EXISTS idx_disputes_customer ON disputes(customer_id);
CREATE INDEX IF NOT EXISTS idx_disputes_status ON disputes(status);

-- Knowledge Articles
CREATE TABLE IF NOT EXISTS knowledge_articles (
    article_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    content TEXT,
    relevance_score REAL DEFAULT 0.0
);

-- Audit Trail (immutable compliance log)
CREATE TABLE IF NOT EXISTS audit_trail (
    entry_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    correlation_id TEXT,
    session_id TEXT,
    procedure_id TEXT,
    step_id TEXT,
    before_state TEXT,
    after_state TEXT,
    metadata TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_trail_actor ON audit_trail(actor);
CREATE INDEX IF NOT EXISTS idx_audit_trail_action ON audit_trail(action);
CREATE INDEX IF NOT EXISTS idx_audit_trail_timestamp ON audit_trail(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_trail_session ON audit_trail(session_id);
"""


def configure_db_path(path: Path) -> None:
    """Override the default database path (called from settings at startup)."""
    global DB_PATH
    DB_PATH = path
    logger.info("Database path configured: %s", DB_PATH)


async def get_connection() -> aiosqlite.Connection:
    """Get a shared database connection (simple pool for SQLite).

    For production with PostgreSQL, replace this with SQLAlchemy
    async session factory with proper connection pooling.
    """
    global _connection_pool
    if _connection_pool is None:
        _connection_pool = await aiosqlite.connect(DB_PATH)
        _connection_pool.row_factory = aiosqlite.Row
        # Enable WAL mode for better concurrent read performance
        await _connection_pool.execute("PRAGMA journal_mode=WAL")
        await _connection_pool.execute("PRAGMA foreign_keys=ON")
        logger.info("Database connection pool initialized")
    return _connection_pool


async def close_connection() -> None:
    """Close the shared database connection (call on shutdown)."""
    global _connection_pool
    if _connection_pool is not None:
        await _connection_pool.close()
        _connection_pool = None
        logger.info("Database connection pool closed")


async def init_db() -> Path:
    """Create all tables if they don't exist. Returns the DB path."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_SCHEMA)
        await db.commit()
    logger.info("Database initialized at %s", DB_PATH)
    return DB_PATH


def get_db():
    """Return an aiosqlite connection context manager.

    Note: Prefer get_connection() for pooled access. This function
    is kept for backward compatibility with existing code.
    """
    return aiosqlite.connect(DB_PATH)


async def query_one(sql: str, params: tuple = ()) -> dict | None:
    """Fetch a single row as a dict, or None if not found."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql, params) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            return dict(row)


async def query_all(sql: str, params: tuple = ()) -> list[dict]:
    """Fetch all rows as a list of dicts."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def execute(sql: str, params: tuple = ()) -> int:
    """Execute an insert/update and return lastrowid."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(sql, params) as cursor:
            await db.commit()
            return cursor.lastrowid


async def execute_in_transaction(statements: list[tuple[str, tuple]]) -> None:
    """Execute multiple statements in a single transaction.

    Args:
        statements: List of (sql, params) tuples to execute atomically.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            for sql, params in statements:
                await db.execute(sql, params)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
