"""Repository pattern for database access.

Provides typed data access objects that abstract raw SQL from business logic.
This allows swapping the underlying database (SQLite -> PostgreSQL) without
changing tools or business code.
"""

from datetime import datetime, timedelta
from typing import Any, Optional

from .db import execute, query_all, query_one
from ..logging_config import get_logger

logger = get_logger("repository")


class OrderRepository:
    """Data access for orders and order items."""

    @staticmethod
    async def get_by_id(order_id: str) -> Optional[dict]:
        """Fetch an order with customer info by order ID."""
        return await query_one(
            """
            SELECT o.*, c.name AS customer_name, c.email
            FROM orders o
            JOIN customers c ON o.customer_id = c.customer_id
            WHERE o.order_id = ?
            """,
            (order_id,),
        )

    @staticmethod
    async def get_items(order_id: str) -> list[dict]:
        """Fetch all items for an order."""
        return await query_all(
            "SELECT name, sku, qty, price FROM order_items WHERE order_id = ?",
            (order_id,),
        )

    @staticmethod
    async def search(
        customer_id: str,
        merchant_name: Optional[str] = None,
        amount: Optional[float] = None,
        date: Optional[str] = None,
    ) -> list[dict]:
        """Search orders with flexible filters."""
        conditions = ["o.customer_id = ?"]
        params: list[Any] = [customer_id]

        if merchant_name:
            conditions.append("o.merchant_name LIKE ?")
            params.append(f"%{merchant_name}%")

        if amount is not None and amount > 0:
            lower = amount * 0.9
            upper = amount * 1.1
            conditions.append("o.total BETWEEN ? AND ?")
            params.extend([lower, upper])

        if date:
            try:
                target = datetime.fromisoformat(date)
                date_lower = (target - timedelta(days=3)).strftime("%Y-%m-%d")
                date_upper = (target + timedelta(days=3)).strftime("%Y-%m-%d")
                conditions.append("o.order_date BETWEEN ? AND ?")
                params.extend([date_lower, date_upper])
            except ValueError:
                conditions.append("o.order_date = ?")
                params.append(date)

        where_clause = " AND ".join(conditions)
        return await query_all(
            f"""
            SELECT o.order_id, o.merchant_name, o.total, o.status, o.order_date,
                   o.delivery_date, o.days_since_delivery, o.payment_method,
                   o.shipping_address, o.customer_id
            FROM orders o
            WHERE {where_clause}
            ORDER BY o.order_date DESC
            """,
            tuple(params),
        )


class CustomerRepository:
    """Data access for customers."""

    @staticmethod
    async def get_by_id(customer_id: str) -> Optional[dict]:
        """Fetch a customer profile by ID."""
        return await query_one(
            "SELECT * FROM customers WHERE customer_id = ?",
            (customer_id,),
        )

    @staticmethod
    async def list_all() -> list[dict]:
        """List all customers (ID and name only)."""
        return await query_all("SELECT customer_id, name FROM customers")


class RefundRepository:
    """Data access for refunds."""

    @staticmethod
    async def create(
        refund_id: str,
        order_id: str,
        amount: float,
        reason: str,
        refund_method: str,
        processed_at: str,
    ) -> int:
        """Insert a new refund record."""
        return await execute(
            """
            INSERT INTO refunds (refund_id, order_id, amount, currency, status, reason,
                                 refund_method, estimated_days, processed_at)
            VALUES (?, ?, ?, 'USD', 'processed', ?, ?, '5-7 business days', ?)
            """,
            (refund_id, order_id, amount, reason, refund_method, processed_at),
        )

    @staticmethod
    async def get_by_order(order_id: str) -> Optional[dict]:
        """Return the single idempotent refund for an order, if present."""
        return await query_one("SELECT * FROM refunds WHERE order_id = ?", (order_id,))


class CaseRepository:
    """Data access for cases and case notes."""

    @staticmethod
    async def get_by_id(case_id: str) -> Optional[dict]:
        """Fetch a case by ID."""
        return await query_one("SELECT * FROM cases WHERE case_id = ?", (case_id,))

    @staticmethod
    async def upsert(case_id: str, status: str, notes: str, customer_id: Optional[str] = None) -> None:
        """Create or update a case."""
        now = datetime.now().isoformat()
        existing = await query_one("SELECT case_id FROM cases WHERE case_id = ?", (case_id,))
        if existing:
            await execute(
                "UPDATE cases SET status = ?, notes = ?, updated_at = ? WHERE case_id = ?",
                (status, notes, now, case_id),
            )
        else:
            await execute(
                "INSERT INTO cases (case_id, customer_id, status, notes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (case_id, customer_id, status, notes, now, now),
            )

    @staticmethod
    async def add_note(note_id: str, case_id: str, note: str, created_by: str = "system") -> None:
        """Add a note to a case."""
        now = datetime.now().isoformat()
        await execute(
            "INSERT INTO case_notes (note_id, case_id, note, created_at, created_by) VALUES (?, ?, ?, ?, ?)",
            (note_id, case_id, note, now, created_by),
        )


class EscalationRepository:
    """Data access for escalations."""

    @staticmethod
    async def create(
        escalation_id: str,
        case_id: str,
        reason: str,
        priority: str,
        assigned_to: str,
        estimated_response: str,
    ) -> None:
        """Create a new escalation."""
        now = datetime.now().isoformat()
        await execute(
            """
            INSERT INTO escalations (escalation_id, case_id, reason, priority,
                                     assigned_to, estimated_response, escalated_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'escalated')
            """,
            (escalation_id, case_id, reason, priority, assigned_to, estimated_response, now),
        )


class FraudAlertRepository:
    """Data access for fraud alerts."""

    @staticmethod
    async def get_by_id(alert_id: str) -> Optional[dict]:
        """Fetch a fraud alert by ID."""
        return await query_one(
            "SELECT * FROM fraud_alerts WHERE alert_id = ?",
            (alert_id,),
        )

    @staticmethod
    async def close(alert_id: str) -> None:
        """Close a fraud alert."""
        await execute(
            "UPDATE fraud_alerts SET status = 'closed' WHERE alert_id = ?",
            (alert_id,),
        )


class AccountRepository:
    """Data access for accounts."""

    @staticmethod
    async def get_by_id(account_id: str) -> Optional[dict]:
        """Fetch an account by ID."""
        return await query_one(
            "SELECT * FROM accounts WHERE account_id = ?",
            (account_id,),
        )

    @staticmethod
    async def update_status(account_id: str, status: str) -> None:
        """Update account status."""
        await execute(
            "UPDATE accounts SET status = ? WHERE account_id = ?",
            (status, account_id),
        )


class TransactionRepository:
    """Data access for transactions."""

    @staticmethod
    async def get_by_account(account_id: str) -> list[dict]:
        """Fetch all transactions for an account, newest first."""
        return await query_all(
            "SELECT * FROM transactions WHERE account_id = ? ORDER BY date DESC",
            (account_id,),
        )


class DeviceRepository:
    """Data access for devices and login history."""

    @staticmethod
    async def get_devices(account_id: str) -> list[dict]:
        """Fetch all devices for an account."""
        return await query_all(
            "SELECT * FROM devices WHERE account_id = ?",
            (account_id,),
        )

    @staticmethod
    async def get_login_history(account_id: str) -> list[dict]:
        """Fetch login history for an account, newest first."""
        return await query_all(
            "SELECT * FROM login_history WHERE account_id = ? ORDER BY timestamp DESC",
            (account_id,),
        )

    @staticmethod
    async def get_risk_indicators(account_id: str) -> list[str]:
        """Fetch risk indicators for an account."""
        rows = await query_all(
            "SELECT indicator FROM risk_indicators WHERE account_id = ?",
            (account_id,),
        )
        return [r["indicator"] for r in rows]


class KnowledgeRepository:
    """Data access for knowledge articles."""

    @staticmethod
    async def search(query: str) -> list[dict]:
        """Search knowledge articles by keyword matching."""
        all_articles = await query_all(
            "SELECT article_id, title, summary, relevance_score FROM knowledge_articles ORDER BY relevance_score DESC"
        )
        query_lower = query.lower()
        matched = [
            article for article in all_articles
            if any(
                word in article["title"].lower() or word in article["summary"].lower()
                for word in query_lower.split()
            )
        ]
        return matched if matched else all_articles[:2]


class DisputeRepository:
    """Data access for EFT disputes (Reg E compliance)."""

    @staticmethod
    async def get_by_id(dispute_id: str) -> Optional[dict]:
        """Fetch a dispute by ID."""
        return await query_one(
            "SELECT * FROM disputes WHERE dispute_id = ?",
            (dispute_id,),
        )

    @staticmethod
    async def get_by_customer(customer_id: str) -> list[dict]:
        """Fetch all disputes for a customer."""
        return await query_all(
            "SELECT * FROM disputes WHERE customer_id = ? ORDER BY reported_date DESC",
            (customer_id,),
        )

    @staticmethod
    async def get_by_transaction(transaction_id: str) -> Optional[dict]:
        """Fetch a dispute by transaction ID."""
        return await query_one(
            "SELECT * FROM disputes WHERE transaction_id = ?",
            (transaction_id,),
        )

    @staticmethod
    async def create(
        dispute_id: str,
        customer_id: str,
        transaction_id: str,
        account_id: str,
        dispute_type: str,
        amount: float,
        merchant: str,
        transaction_date: str,
        reported_date: str,
        statement_date: str,
        days_since_transaction: int,
        days_since_statement: int,
        liability_tier: str,
        max_liability: float,
        investigation_deadline: str,
        payment_method: str,
        metadata: Optional[str] = None,
    ) -> int:
        """Create a new dispute record."""
        return await execute(
            """
            INSERT INTO disputes (dispute_id, customer_id, transaction_id, account_id,
                                  dispute_type, amount, merchant, transaction_date,
                                  reported_date, statement_date, days_since_transaction,
                                  days_since_statement, liability_tier, max_liability,
                                  investigation_deadline, payment_method, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (dispute_id, customer_id, transaction_id, account_id, dispute_type,
             amount, merchant, transaction_date, reported_date, statement_date,
             days_since_transaction, days_since_statement, liability_tier,
             max_liability, investigation_deadline, payment_method, metadata),
        )

    @staticmethod
    async def update_status(dispute_id: str, status: str, **kwargs) -> None:
        """Update dispute status and optional fields."""
        sets = ["status = ?"]
        params: list = [status]
        for key, val in kwargs.items():
            if val is not None:
                sets.append(f"{key} = ?")
                params.append(val)
        params.append(dispute_id)
        await execute(
            f"UPDATE disputes SET {', '.join(sets)} WHERE dispute_id = ?",
            tuple(params),
        )

    @staticmethod
    async def issue_provisional_credit(
        dispute_id: str, amount: float, credit_date: str,
    ) -> None:
        """Record provisional credit issuance."""
        await execute(
            """
            UPDATE disputes SET provisional_credit_issued = 1,
                                provisional_credit_amount = ?,
                                provisional_credit_date = ?,
                                status = 'provisional_credit'
            WHERE dispute_id = ?
            """,
            (amount, credit_date, dispute_id),
        )


class AuditRepository:
    """Data access for audit trail entries."""

    @staticmethod
    async def write(entry: dict) -> None:
        """Persist an audit trail entry to the database."""
        import json
        await execute(
            """
            INSERT INTO audit_trail (entry_id, timestamp, action, actor, resource_type,
                                     resource_id, correlation_id, session_id, procedure_id,
                                     step_id, before_state, after_state, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.get("entry_id"),
                entry.get("timestamp"),
                entry.get("action"),
                entry.get("actor"),
                entry.get("resource_type"),
                entry.get("resource_id"),
                entry.get("correlation_id"),
                entry.get("session_id"),
                entry.get("procedure_id"),
                entry.get("step_id"),
                json.dumps(entry.get("before_state")) if entry.get("before_state") else None,
                json.dumps(entry.get("after_state")) if entry.get("after_state") else None,
                json.dumps(entry.get("metadata")) if entry.get("metadata") else None,
            ),
        )
