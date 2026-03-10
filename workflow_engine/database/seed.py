"""Seed all mock data into the SQLite database."""

from datetime import datetime, timedelta

import aiosqlite

from workflow_engine.database.db import DB_PATH


async def seed_all() -> None:
    """Insert all mock data into the database. Idempotent via INSERT OR IGNORE."""
    async with aiosqlite.connect(DB_PATH) as db:
        await _seed_customers(db)
        await _seed_orders(db)
        await _seed_order_items(db)
        await _seed_accounts(db)
        await _seed_transactions(db)
        await _seed_fraud_alerts(db)
        await _seed_devices(db)
        await _seed_login_history(db)
        await _seed_risk_indicators(db)
        await _seed_knowledge_articles(db)
        await _seed_disputes(db)
        await db.commit()


async def _seed_customers(db: aiosqlite.Connection) -> None:
    customers = [
        ("CUST-456", "Jane Smith", "jane.smith@email.com", "+1-555-0123", "active", "gold", 15, "2022-03-15"),
        ("CUST-789", "Bob Johnson", "bob.j@email.com", "+1-555-0456", "active", "silver", 7, "2023-06-20"),
        ("CUST-012", "Alice Williams", "alice.w@email.com", "+1-555-0789", "active", "bronze", 3, "2024-01-10"),
        ("CUST-345", "Carol Davis", "carol.d@email.com", "+1-555-0345", "active", "bronze", 5, "2023-09-01"),
    ]
    await db.executemany(
        "INSERT OR IGNORE INTO customers (customer_id, name, email, phone, account_status, loyalty_tier, total_orders, member_since) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        customers,
    )


async def _seed_orders(db: aiosqlite.Connection) -> None:
    now = datetime.now()
    orders = [
        ("ORD-123", "CUST-456", "TechMart Electronics", 79.99, "delivered", (now - timedelta(days=10)).strftime("%Y-%m-%d"), (now - timedelta(days=5)).strftime("%Y-%m-%d"), 5, "credit_card_ending_4242", "123 Main St, Springfield, IL 62701"),
        ("ORD-456", "CUST-789", "SportZone", 155.97, "shipped", (now - timedelta(days=3)).strftime("%Y-%m-%d"), None, 0, "paypal", "456 Oak Ave, Portland, OR 97201"),
        ("ORD-789", "CUST-012", "GadgetWorld", 249.99, "processing", now.strftime("%Y-%m-%d"), None, 0, "credit_card_ending_1234", "789 Pine Rd, Austin, TX 78701"),
        ("ORD-999", "CUST-345", "HomeOffice Supplies", 49.99, "delivered", (now - timedelta(days=45)).strftime("%Y-%m-%d"), (now - timedelta(days=40)).strftime("%Y-%m-%d"), 40, "debit_card_ending_5678", "321 Elm St, Denver, CO 80201"),
    ]
    await db.executemany(
        "INSERT OR REPLACE INTO orders (order_id, customer_id, merchant_name, total, status, order_date, delivery_date, days_since_delivery, payment_method, shipping_address) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        orders,
    )


async def _seed_order_items(db: aiosqlite.Connection) -> None:
    # Check if already seeded
    async with db.execute("SELECT COUNT(*) FROM order_items") as cur:
        count = (await cur.fetchone())[0]
    if count > 0:
        return

    items = [
        ("ORD-123", "Wireless Headphones", "WH-100", 1, 79.99),
        ("ORD-456", "Running Shoes", "RS-200", 1, 129.99),
        ("ORD-456", "Athletic Socks", "AS-050", 2, 12.99),
        ("ORD-789", "Smart Watch", "SW-300", 1, 249.99),
        ("ORD-999", "Laptop Stand", "LS-400", 1, 49.99),
    ]
    await db.executemany(
        "INSERT INTO order_items (order_id, name, sku, qty, price) VALUES (?, ?, ?, ?, ?)",
        items,
    )


async def _seed_accounts(db: aiosqlite.Connection) -> None:
    accounts = [
        ("ACCT-1001", "Michael Chen", "michael.chen@email.com", "active"),
        ("ACCT-2002", "Sarah Parker", "sarah.parker@email.com", "active"),
        ("ACCT-3003", "David Lee", "david.lee@email.com", "active"),
        ("ACCT-4004", "Emily Brown", "emily.brown@email.com", "active"),
    ]
    await db.executemany(
        "INSERT OR IGNORE INTO accounts (account_id, customer_name, email, status) VALUES (?, ?, ?, ?)",
        accounts,
    )


async def _seed_transactions(db: aiosqlite.Connection) -> None:
    now = datetime.now()
    transactions = [
        # ACCT-1001
        ("TXN-5001", "ACCT-1001", 1500.00, "ElectroMart Online", (now - timedelta(hours=2)).isoformat(), "New York, NY", 1, "purchase"),
        ("TXN-5002", "ACCT-1001", 2000.00, "TechGear Pro", (now - timedelta(hours=1, minutes=45)).isoformat(), "Los Angeles, CA", 1, "purchase"),
        ("TXN-5003", "ACCT-1001", 1000.00, "Digital World", (now - timedelta(hours=1, minutes=30)).isoformat(), "Chicago, IL", 1, "purchase"),
        ("TXN-5004", "ACCT-1001", 55.00, "Coffee Shop", (now - timedelta(days=1)).isoformat(), "New York, NY", 0, "purchase"),
        ("TXN-5005", "ACCT-1001", 120.00, "Grocery Store", (now - timedelta(days=2)).isoformat(), "New York, NY", 0, "purchase"),
        # ACCT-2002
        ("TXN-6001", "ACCT-2002", 2899.99, "Premium Electronics", (now - timedelta(hours=1)).isoformat(), "Miami, FL", 1, "purchase"),
        ("TXN-6002", "ACCT-2002", 45.00, "Local Restaurant", (now - timedelta(days=1)).isoformat(), "Seattle, WA", 0, "purchase"),
        ("TXN-6003", "ACCT-2002", 89.99, "Streaming Service", (now - timedelta(days=5)).isoformat(), "Online", 0, "subscription"),
        # ACCT-3003
        ("TXN-7001", "ACCT-3003", 899.99, "TechHub Store", (now - timedelta(hours=6)).isoformat(), "Portland, OR", 1, "purchase"),
        ("TXN-7002", "ACCT-3003", 32.50, "Bookstore", (now - timedelta(days=2)).isoformat(), "Portland, OR", 0, "purchase"),
        ("TXN-7003", "ACCT-3003", 15.99, "Music Streaming", (now - timedelta(days=7)).isoformat(), "Online", 0, "subscription"),
    ]
    await db.executemany(
        "INSERT OR REPLACE INTO transactions (txn_id, account_id, amount, merchant, date, location, is_flagged, type) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        transactions,
    )


async def _seed_fraud_alerts(db: aiosqlite.Connection) -> None:
    now = datetime.now()
    alerts = [
        ("FA-001", "card_not_present", "high", 87, "ACCT-1001", "Michael Chen", (now - timedelta(hours=2)).isoformat(), "Multiple high-value transactions from new device in different geographic locations within 30 minutes", 4500.00, 3, "open"),
        ("FA-002", "account_takeover", "high", 92, "ACCT-2002", "Sarah Parker", (now - timedelta(hours=1)).isoformat(), "Password changed followed by shipping address update and large purchase from unrecognized device", 2899.99, 1, "open"),
        ("FA-003", "unusual_activity", "medium", 55, "ACCT-3003", "David Lee", (now - timedelta(hours=6)).isoformat(), "Purchase pattern deviation - electronics purchase significantly above average order value", 899.99, 1, "open"),
        ("FA-004", "unusual_activity", "low", 25, "ACCT-4004", "Emily Brown", (now - timedelta(hours=12)).isoformat(), "Minor velocity check trigger - 3 small transactions in quick succession at same merchant", 45.97, 3, "open"),
    ]
    await db.executemany(
        "INSERT OR REPLACE INTO fraud_alerts (alert_id, type, severity, risk_score, account_id, customer_name, triggered_at, description, amount_involved, transactions_flagged, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        alerts,
    )


async def _seed_devices(db: aiosqlite.Connection) -> None:
    devices = [
        # ACCT-1001
        ("DEV-001", "ACCT-1001", "iPhone 15", "iOS 17", "2023-06-15", 1),
        ("DEV-002", "ACCT-1001", "MacBook Pro", "macOS 14", "2023-06-15", 1),
        # ACCT-2002
        ("DEV-003", "ACCT-2002", "Samsung Galaxy S24", "Android 14", "2024-01-10", 1),
        # ACCT-3003
        ("DEV-005", "ACCT-3003", "Pixel 8", "Android 14", "2024-03-01", 1),
        ("DEV-006", "ACCT-3003", "Chromebook", "ChromeOS", "2024-03-01", 1),
    ]
    await db.executemany(
        "INSERT OR IGNORE INTO devices (device_id, account_id, type, os, first_seen, trusted) VALUES (?, ?, ?, ?, ?, ?)",
        devices,
    )


async def _seed_login_history(db: aiosqlite.Connection) -> None:
    async with db.execute("SELECT COUNT(*) FROM login_history") as cur:
        count = (await cur.fetchone())[0]
    if count > 0:
        return

    now = datetime.now()
    logins = [
        # ACCT-1001
        ("ACCT-1001", "Unknown Android Device", "DEV-NEW-1", "Los Angeles, CA", (now - timedelta(hours=2)).isoformat(), 1, "192.168.1.100"),
        ("ACCT-1001", "iPhone 15", "DEV-001", "New York, NY", (now - timedelta(days=1)).isoformat(), 0, "10.0.0.1"),
        # ACCT-2002
        ("ACCT-2002", "Windows Desktop", "DEV-NEW-2", "Miami, FL", (now - timedelta(hours=1, minutes=30)).isoformat(), 1, "203.0.113.42"),
        ("ACCT-2002", "Samsung Galaxy S24", "DEV-003", "Seattle, WA", (now - timedelta(days=1)).isoformat(), 0, "10.0.0.2"),
        # ACCT-3003
        ("ACCT-3003", "Pixel 8", "DEV-005", "Portland, OR", (now - timedelta(hours=6)).isoformat(), 0, "10.0.0.3"),
    ]
    await db.executemany(
        "INSERT INTO login_history (account_id, device, device_id, location, timestamp, is_new, ip) VALUES (?, ?, ?, ?, ?, ?, ?)",
        logins,
    )


async def _seed_risk_indicators(db: aiosqlite.Connection) -> None:
    async with db.execute("SELECT COUNT(*) FROM risk_indicators") as cur:
        count = (await cur.fetchone())[0]
    if count > 0:
        return

    indicators = [
        ("ACCT-1001", "new_device_login"),
        ("ACCT-1001", "geographic_anomaly"),
        ("ACCT-1001", "multiple_locations_short_timeframe"),
        ("ACCT-2002", "new_device_login"),
        ("ACCT-2002", "password_recently_changed"),
        ("ACCT-2002", "shipping_address_changed"),
        ("ACCT-2002", "geographic_anomaly"),
    ]
    await db.executemany(
        "INSERT INTO risk_indicators (account_id, indicator) VALUES (?, ?)",
        indicators,
    )


async def _seed_knowledge_articles(db: aiosqlite.Connection) -> None:
    articles = [
        ("KB-001", "Refund Policy Overview", "Our standard refund policy allows returns within 30 days of delivery. Items must be in original condition. Non-refundable categories include: personalized items, digital downloads, and clearance items.", None, 0.95),
        ("KB-002", "Escalation Procedures", "Cases should be escalated when: customer requests supervisor, issue exceeds agent authority, complaint involves safety concerns, or case has been open for more than 48 hours.", None, 0.85),
        ("KB-003", "Fraud Investigation Guidelines", "When investigating fraud alerts: gather all available evidence before making a determination, check device fingerprints and transaction patterns, document all findings, and follow the SAR submission timeline requirements.", None, 0.80),
        ("KB-004", "Store Credit Policy", "Store credit can be issued for orders outside the refund window or for non-refundable items at supervisor discretion. Store credit expires after 12 months and cannot be converted to cash.", None, 0.75),
    ]
    await db.executemany(
        "INSERT OR IGNORE INTO knowledge_articles (article_id, title, summary, content, relevance_score) VALUES (?, ?, ?, ?, ?)",
        articles,
    )


async def _seed_disputes(db: aiosqlite.Connection) -> None:
    """Seed EFT dispute data for Reg E compliance testing.

    Test scenarios cover all three Reg E liability tiers and various dispute states:
    - DISP-001: CUST-456 — Unauthorized debit card charge, reported within 2 days (Tier 1: $50 max liability)
    - DISP-002: CUST-789 — Unauthorized ACH transfer, reported at 15 days (Tier 2: $500 max liability)
    - DISP-003: CUST-012 — Unauthorized charge, reported at 75 days (Tier 3: unlimited liability, outside 60-day window)
    - DISP-004: CUST-345 — Error dispute (wrong amount charged), reported within 2 days (Tier 1)
    """
    now = datetime.now()
    disputes = [
        # DISP-001: Tier 1 — reported within 2 business days, max $50 liability
        # Customer Jane Smith noticed unauthorized charge yesterday, debit card
        (
            "DISP-001", "CUST-456", "TXN-EFT-001", "ACCT-1001",
            "unauthorized", 350.00, "Unknown Electronics Store",
            (now - timedelta(days=3)).strftime("%Y-%m-%d"),    # transaction 3 days ago
            (now - timedelta(days=1)).strftime("%Y-%m-%d"),    # reported yesterday (within 2 days of learning)
            (now - timedelta(days=1)).strftime("%Y-%m-%d"),    # statement issued 1 day ago
            3, 1, "tier_1", 50.00,
            (now + timedelta(days=10)).strftime("%Y-%m-%d"),   # investigation deadline
            "debit_card",
            "open", 0, None, None, None, None, None,
        ),
        # DISP-002: Tier 2 — reported at 15 days, max $500 liability
        # Customer Bob Johnson noticed unauthorized ACH withdrawal
        (
            "DISP-002", "CUST-789", "TXN-EFT-002", "ACCT-2002",
            "unauthorized", 1250.00, "Unknown Wire Transfer",
            (now - timedelta(days=20)).strftime("%Y-%m-%d"),   # transaction 20 days ago
            (now - timedelta(days=5)).strftime("%Y-%m-%d"),    # reported 5 days ago (15 days after txn)
            (now - timedelta(days=18)).strftime("%Y-%m-%d"),   # statement 18 days ago
            20, 13, "tier_2", 500.00,
            (now + timedelta(days=5)).strftime("%Y-%m-%d"),    # investigation deadline
            "ach",
            "investigating", 0, None, None, None, None, None,
        ),
        # DISP-003: Tier 3 — reported at 75 days, beyond 60-day window = unlimited liability
        # Customer Alice Williams finally noticed old unauthorized charge
        (
            "DISP-003", "CUST-012", "TXN-EFT-003", "ACCT-3003",
            "unauthorized", 500.00, "Suspicious Online Store",
            (now - timedelta(days=90)).strftime("%Y-%m-%d"),   # transaction 90 days ago
            (now - timedelta(days=2)).strftime("%Y-%m-%d"),    # reported 2 days ago
            (now - timedelta(days=75)).strftime("%Y-%m-%d"),   # statement 75 days ago
            90, 73, "tier_3", 500.00,  # unlimited = full amount
            (now + timedelta(days=8)).strftime("%Y-%m-%d"),
            "debit_card",
            "open", 0, None, None, None, None, None,
        ),
        # DISP-004: Error dispute — wrong amount charged (not unauthorized), Tier 1
        # Customer Carol Davis was charged wrong amount
        (
            "DISP-004", "CUST-345", "TXN-EFT-004", "ACCT-4004",
            "error", 89.99, "HomeOffice Supplies",
            (now - timedelta(days=5)).strftime("%Y-%m-%d"),    # transaction 5 days ago
            (now - timedelta(days=1)).strftime("%Y-%m-%d"),    # reported yesterday
            (now - timedelta(days=2)).strftime("%Y-%m-%d"),    # statement 2 days ago
            5, 1, "tier_1", 50.00,
            (now + timedelta(days=9)).strftime("%Y-%m-%d"),
            "debit_card",
            "open", 0, None, None, None, None, None,
        ),
    ]
    await db.executemany(
        """INSERT OR REPLACE INTO disputes (
            dispute_id, customer_id, transaction_id, account_id,
            dispute_type, amount, merchant, transaction_date,
            reported_date, statement_date,
            days_since_transaction, days_since_statement, liability_tier, max_liability,
            investigation_deadline, payment_method,
            status, provisional_credit_issued, provisional_credit_date,
            provisional_credit_amount, resolution, resolution_date, resolution_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        disputes,
    )

    # Also seed the corresponding EFT transactions into the transactions table
    eft_transactions = [
        ("TXN-EFT-001", "ACCT-1001", 350.00, "Unknown Electronics Store",
         (now - timedelta(days=3)).isoformat(), "Online", 1, "debit"),
        ("TXN-EFT-002", "ACCT-2002", 1250.00, "Unknown Wire Transfer",
         (now - timedelta(days=20)).isoformat(), "ACH", 1, "ach_withdrawal"),
        ("TXN-EFT-003", "ACCT-3003", 500.00, "Suspicious Online Store",
         (now - timedelta(days=90)).isoformat(), "Online", 1, "debit"),
        ("TXN-EFT-004", "ACCT-4004", 89.99, "HomeOffice Supplies",
         (now - timedelta(days=5)).isoformat(), "In-Store", 0, "debit"),
    ]
    await db.executemany(
        "INSERT OR REPLACE INTO transactions (txn_id, account_id, amount, merchant, date, location, is_flagged, type) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        eft_transactions,
    )

    # Add Reg E knowledge article
    await db.execute(
        "INSERT OR IGNORE INTO knowledge_articles (article_id, title, summary, content, relevance_score) VALUES (?, ?, ?, ?, ?)",
        (
            "KB-005",
            "Regulation E — EFT Dispute Rights",
            "Under Regulation E, consumers must report unauthorized electronic fund transfers within 60 days "
            "of the statement date. Liability tiers: within 2 business days = $50 max; within 60 days = $500 max; "
            "beyond 60 days = unlimited. Financial institutions must investigate within 10 business days and may "
            "issue provisional credit if investigation extends beyond 10 days. Final resolution within 45 calendar days "
            "(90 days for new accounts, POS, or foreign transactions).",
            None,
            0.90,
        ),
    )
