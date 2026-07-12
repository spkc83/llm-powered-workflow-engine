"""Tests for the database module (init, seed, query helpers)."""

import pytest

from workflow_engine.database.db import execute, init_db, query_all, query_one
from workflow_engine.database.seed import seed_all
from workflow_engine.database.repository import AuditRepository


@pytest.fixture(autouse=True)
def use_tmp_db(tmp_path, monkeypatch):
    """Point DB_PATH to a temporary file for each test."""
    import workflow_engine.database.db as db_mod
    import workflow_engine.database.seed as seed_mod

    tmp_db = tmp_path / "test.db"
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_db)
    monkeypatch.setattr(seed_mod, "DB_PATH", tmp_db)


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------


class TestInitDb:
    @pytest.mark.asyncio
    async def test_creates_database_file(self, tmp_path):
        path = await init_db()
        assert path.exists()

    @pytest.mark.asyncio
    async def test_creates_customers_table(self):
        await init_db()
        rows = await query_all("SELECT name FROM sqlite_master WHERE type='table' AND name='customers'")
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_creates_all_expected_tables(self):
        await init_db()
        rows = await query_all("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        table_names = {r["name"] for r in rows}
        expected = {
            "customers", "orders", "order_items", "accounts", "transactions",
            "fraud_alerts", "devices", "login_history", "risk_indicators",
            "cases", "case_notes", "escalations", "refunds", "knowledge_articles",
        }
        assert expected.issubset(table_names)

    @pytest.mark.asyncio
    async def test_idempotent(self):
        await init_db()
        await init_db()  # Should not raise
        rows = await query_all("SELECT name FROM sqlite_master WHERE type='table' AND name='customers'")
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_orders_table_has_merchant_name_column(self):
        await init_db()
        rows = await query_all("PRAGMA table_info(orders)")
        column_names = [r["name"] for r in rows]
        assert "merchant_name" in column_names

    @pytest.mark.asyncio
    async def test_audit_hash_chain_detects_content_tampering(self):
        await init_db()
        await AuditRepository.write(
            {
                "entry_id": "AUD-1",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "action": "case.updated",
                "actor": "rep-1",
                "resource_type": "case",
                "resource_id": "CASE-1",
                "metadata": {"status": "open"},
            }
        )
        await AuditRepository.write(
            {
                "entry_id": "AUD-2",
                "timestamp": "2026-01-01T00:01:00+00:00",
                "action": "case.updated",
                "actor": "rep-1",
                "resource_type": "case",
                "resource_id": "CASE-1",
                "metadata": {"status": "closed"},
            }
        )
        assert (await AuditRepository.verify_chain())["valid"] is True

        await execute(
            "UPDATE audit_trail SET actor='tampered' WHERE entry_id='AUD-1'"
        )
        result = await AuditRepository.verify_chain()
        assert result["valid"] is False
        assert result["broken_entry_id"] == "AUD-1"


# ---------------------------------------------------------------------------
# seed_all
# ---------------------------------------------------------------------------


class TestSeedAll:
    @pytest.mark.asyncio
    async def test_seeds_customers(self):
        await init_db()
        await seed_all()
        rows = await query_all("SELECT * FROM customers")
        assert len(rows) >= 3

    @pytest.mark.asyncio
    async def test_seeds_orders(self):
        await init_db()
        await seed_all()
        rows = await query_all("SELECT * FROM orders")
        assert len(rows) == 4

    @pytest.mark.asyncio
    async def test_seeds_order_items(self):
        await init_db()
        await seed_all()
        rows = await query_all("SELECT * FROM order_items")
        assert len(rows) == 5

    @pytest.mark.asyncio
    async def test_seeds_accounts(self):
        await init_db()
        await seed_all()
        rows = await query_all("SELECT * FROM accounts")
        assert len(rows) == 4

    @pytest.mark.asyncio
    async def test_seeds_transactions(self):
        await init_db()
        await seed_all()
        rows = await query_all("SELECT * FROM transactions")
        assert len(rows) == 15  # 11 original + 4 EFT dispute transactions

    @pytest.mark.asyncio
    async def test_seeds_fraud_alerts(self):
        await init_db()
        await seed_all()
        rows = await query_all("SELECT * FROM fraud_alerts")
        assert len(rows) == 4

    @pytest.mark.asyncio
    async def test_seeds_devices(self):
        await init_db()
        await seed_all()
        rows = await query_all("SELECT * FROM devices")
        assert len(rows) == 5

    @pytest.mark.asyncio
    async def test_seeds_knowledge_articles(self):
        await init_db()
        await seed_all()
        rows = await query_all("SELECT * FROM knowledge_articles")
        assert len(rows) == 5  # 4 original + 1 Reg E article

    @pytest.mark.asyncio
    async def test_idempotent(self):
        await init_db()
        await seed_all()
        await seed_all()  # Run twice
        rows = await query_all("SELECT * FROM customers")
        assert len(rows) >= 3  # No duplicates


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


class TestQueryHelpers:
    @pytest.mark.asyncio
    async def test_query_one_returns_dict(self):
        await init_db()
        await seed_all()
        row = await query_one("SELECT * FROM customers WHERE customer_id = ?", ("CUST-456",))
        assert isinstance(row, dict)
        assert row["name"] == "Jane Smith"

    @pytest.mark.asyncio
    async def test_query_one_returns_none_for_missing(self):
        await init_db()
        row = await query_one("SELECT * FROM customers WHERE customer_id = ?", ("NONEXISTENT",))
        assert row is None

    @pytest.mark.asyncio
    async def test_query_all_returns_list(self):
        await init_db()
        await seed_all()
        rows = await query_all("SELECT * FROM orders")
        assert isinstance(rows, list)
        assert all(isinstance(r, dict) for r in rows)

    @pytest.mark.asyncio
    async def test_query_all_returns_empty_list(self):
        await init_db()
        rows = await query_all("SELECT * FROM refunds")
        assert rows == []

    @pytest.mark.asyncio
    async def test_execute_inserts_row(self):
        await init_db()
        await execute(
            "INSERT INTO customers (customer_id, name, email, member_since) VALUES (?, ?, ?, ?)",
            ("TEST-1", "Test User", "test@test.com", "2024-01-01"),
        )
        row = await query_one("SELECT * FROM customers WHERE customer_id = ?", ("TEST-1",))
        assert row is not None
        assert row["name"] == "Test User"
