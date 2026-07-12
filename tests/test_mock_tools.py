"""Tests for tool functions (CRM, fraud, common) backed by SQLite.

Each test uses a temporary in-memory-like SQLite DB via monkeypatch.
"""

import pytest
import pytest_asyncio
from unittest.mock import MagicMock

from workflow_engine.database.db import init_db
from workflow_engine.database.seed import seed_all
from workflow_engine.auth.models import Permission


def make_tool_context(initial_state=None):
    """Return a mock object that behaves like ADK ToolContext for testing."""
    ctx = MagicMock()
    state = dict(initial_state or {})
    state.setdefault("actor_permissions", [permission.value for permission in Permission])
    state.setdefault("refund_consent_evidence", "test:explicit-consent")
    ctx.state = state
    return ctx


@pytest_asyncio.fixture(autouse=True)
async def setup_db(tmp_path, monkeypatch):
    """Point DB_PATH to a temporary file and seed it before each test."""
    import workflow_engine.database.db as db_mod
    import workflow_engine.database.seed as seed_mod

    tmp_db = tmp_path / "test.db"
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_db)
    monkeypatch.setattr(seed_mod, "DB_PATH", tmp_db)

    await init_db()
    await seed_all()


# ---------------------------------------------------------------------------
# CRM tools
# ---------------------------------------------------------------------------

from workflow_engine.tools.crm_tools import (
    get_customer_profile,
    issue_refund,
    lookup_order,
    search_orders,
    update_case_status,
)


class TestLookupOrder:
    @pytest.mark.asyncio
    async def test_returns_known_order(self):
        ctx = make_tool_context()
        result = await lookup_order("ORD-123", ctx)
        assert result["found"] is True
        assert result["order_id"] == "ORD-123"
        assert result["customer_name"] == "Jane Smith"

    @pytest.mark.asyncio
    async def test_returns_error_for_unknown_order(self):
        ctx = make_tool_context()
        result = await lookup_order("ORD-UNKNOWN", ctx)
        assert result["found"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_stores_order_data_in_state(self):
        ctx = make_tool_context()
        await lookup_order("ORD-123", ctx)
        assert ctx.state["order_data"]["order_id"] == "ORD-123"

    @pytest.mark.asyncio
    async def test_stores_customer_id_in_state(self):
        ctx = make_tool_context()
        await lookup_order("ORD-123", ctx)
        assert ctx.state["customer_id"] == "CUST-456"

    @pytest.mark.asyncio
    async def test_all_known_orders_return_found(self):
        for order_id in ["ORD-123", "ORD-456", "ORD-789", "ORD-999"]:
            ctx = make_tool_context()
            result = await lookup_order(order_id, ctx)
            assert result["found"] is True, f"{order_id} should be found"

    @pytest.mark.asyncio
    async def test_order_items_returned(self):
        ctx = make_tool_context()
        result = await lookup_order("ORD-456", ctx)
        assert len(result["items"]) == 2

    @pytest.mark.asyncio
    async def test_merchant_name_in_result(self):
        ctx = make_tool_context()
        result = await lookup_order("ORD-123", ctx)
        assert result["merchant_name"] == "TechMart Electronics"

    @pytest.mark.asyncio
    async def test_rejects_order_for_wrong_customer(self):
        """lookup_order must verify that the order belongs to the session customer."""
        ctx = make_tool_context({"customer_id": "CUST-789"})
        result = await lookup_order("ORD-123", ctx)  # ORD-123 belongs to CUST-456
        assert result["found"] is False
        assert "order_data" not in ctx.state

    @pytest.mark.asyncio
    async def test_allows_order_for_correct_customer(self):
        """lookup_order succeeds when session customer matches order owner."""
        ctx = make_tool_context({"customer_id": "CUST-456"})
        result = await lookup_order("ORD-123", ctx)  # ORD-123 belongs to CUST-456
        assert result["found"] is True
        assert ctx.state["order_data"]["order_id"] == "ORD-123"

    @pytest.mark.asyncio
    async def test_allows_order_when_no_session_customer(self):
        """lookup_order works without session customer_id (backward compat)."""
        ctx = make_tool_context()
        result = await lookup_order("ORD-123", ctx)
        assert result["found"] is True


class TestSearchOrders:
    @pytest.mark.asyncio
    async def test_finds_order_by_merchant_name(self):
        ctx = make_tool_context({"customer_id": "CUST-456"})
        result = await search_orders("CUST-456", ctx, merchant_name="TechMart")
        assert result["count"] == 1
        assert result["matches"][0]["order_id"] == "ORD-123"

    @pytest.mark.asyncio
    async def test_finds_order_by_approximate_amount(self):
        ctx = make_tool_context({"customer_id": "CUST-456"})
        result = await search_orders("CUST-456", ctx, amount=80)
        assert result["count"] == 1
        assert result["matches"][0]["order_id"] == "ORD-123"

    @pytest.mark.asyncio
    async def test_returns_empty_for_wrong_customer(self):
        ctx = make_tool_context({"customer_id": "CUST-789"})
        result = await search_orders("CUST-789", ctx, merchant_name="TechMart")
        assert result["count"] == 0
        assert result["matches"] == []

    @pytest.mark.asyncio
    async def test_returns_multiple_matches_when_ambiguous(self):
        ctx = make_tool_context({"customer_id": "CUST-456"})
        result = await search_orders("CUST-456", ctx)
        assert result["count"] >= 1
        assert isinstance(result["matches"], list)

    @pytest.mark.asyncio
    async def test_stores_order_data_when_single_match(self):
        ctx = make_tool_context({"customer_id": "CUST-456"})
        await search_orders("CUST-456", ctx, merchant_name="TechMart")
        assert "order_data" in ctx.state
        assert ctx.state["order_data"]["order_id"] == "ORD-123"
        assert ctx.state["customer_id"] == "CUST-456"

    @pytest.mark.asyncio
    async def test_returns_not_found_for_no_matches(self):
        ctx = make_tool_context({"customer_id": "CUST-456"})
        result = await search_orders("CUST-456", ctx, merchant_name="NonexistentStore")
        assert result["count"] == 0
        assert "No orders found" in result["message"]

    @pytest.mark.asyncio
    async def test_falls_back_without_date_when_date_misses(self):
        """If the date filter is too narrow, retry without it using merchant_name."""
        ctx = make_tool_context({"customer_id": "CUST-345"})
        # Use a date far from any order — fallback should still find by merchant
        result = await search_orders("CUST-345", ctx, merchant_name="HomeOffice", date="2020-01-01")
        assert result["count"] == 1
        assert result["matches"][0]["order_id"] == "ORD-999"


class TestGetCustomerProfile:
    @pytest.mark.asyncio
    async def test_returns_known_customer(self):
        ctx = make_tool_context({"customer_id": "CUST-456"})
        result = await get_customer_profile("CUST-456", ctx)
        assert result["found"] is True
        assert result["name"] == "Jane Smith"

    @pytest.mark.asyncio
    async def test_returns_error_for_unknown_customer(self):
        ctx = make_tool_context({"customer_id": "CUST-UNKNOWN"})
        result = await get_customer_profile("CUST-UNKNOWN", ctx)
        assert result["found"] is False

    @pytest.mark.asyncio
    async def test_stores_customer_data_in_state(self):
        ctx = make_tool_context({"customer_id": "CUST-456"})
        await get_customer_profile("CUST-456", ctx)
        assert ctx.state["customer_data"]["customer_id"] == "CUST-456"

    @pytest.mark.asyncio
    async def test_loyalty_tier_present(self):
        ctx = make_tool_context({"customer_id": "CUST-456"})
        result = await get_customer_profile("CUST-456", ctx)
        assert "loyalty_tier" in result


class TestIssueRefund:
    @pytest.mark.asyncio
    async def test_returns_refund_id(self):
        ctx = make_tool_context({"customer_id": "CUST-456"})
        result = await issue_refund("ORD-123", "defective item", ctx)
        assert "refund_id" in result
        assert result["refund_id"].startswith("REF-")

    @pytest.mark.asyncio
    async def test_reloads_order_total_instead_of_trusting_session_state(self):
        ctx = make_tool_context({
            "customer_id": "CUST-456",
            "order_data": {"total": 1.00, "payment_method": "attacker_controlled"},
        })
        result = await issue_refund("ORD-123", "wrong item", ctx)
        assert result["amount"] == 79.99

    @pytest.mark.asyncio
    async def test_status_is_processed(self):
        ctx = make_tool_context({"customer_id": "CUST-456"})
        result = await issue_refund("ORD-123", "changed mind", ctx)
        assert result["status"] == "processed"

    @pytest.mark.asyncio
    async def test_stores_refund_data_in_state(self):
        ctx = make_tool_context({"customer_id": "CUST-456"})
        await issue_refund("ORD-123", "reason", ctx)
        assert "refund_data" in ctx.state

    @pytest.mark.asyncio
    async def test_sets_workflow_status_in_state(self):
        ctx = make_tool_context({"customer_id": "CUST-456"})
        await issue_refund("ORD-123", "reason", ctx)
        assert ctx.state["workflow_status"] == "refund_processed"

    @pytest.mark.asyncio
    async def test_denies_when_verified_customer_context_is_missing(self):
        ctx = make_tool_context()
        result = await issue_refund("ORD-123", "reason", ctx)
        assert result["status"] == "not_authorized"


class TestUpdateCaseStatus:
    @pytest.mark.asyncio
    async def test_returns_case_id(self):
        ctx = make_tool_context()
        result = await update_case_status("CASE-001", "resolved", "all done", ctx)
        assert result["case_id"] == "CASE-001"

    @pytest.mark.asyncio
    async def test_returns_correct_status(self):
        ctx = make_tool_context()
        result = await update_case_status("CASE-001", "escalated", "needs supervisor", ctx)
        assert result["status"] == "escalated"

    @pytest.mark.asyncio
    async def test_stores_status_in_state(self):
        ctx = make_tool_context()
        await update_case_status("CASE-001", "closed", "resolved", ctx)
        assert ctx.state["case_status"] == "closed"
        assert ctx.state["workflow_status"] == "closed"


# ---------------------------------------------------------------------------
# Fraud tools
# ---------------------------------------------------------------------------

from workflow_engine.tools.fraud_tools import (
    check_device_fingerprint,
    close_alert,
    flag_account,
    get_account_transactions,
    get_fraud_alert,
    submit_sar,
)


class TestGetFraudAlert:
    @pytest.mark.asyncio
    async def test_returns_known_alert(self):
        ctx = make_tool_context()
        result = await get_fraud_alert("FA-001", ctx)
        assert result["found"] is True
        assert result["alert_id"] == "FA-001"

    @pytest.mark.asyncio
    async def test_returns_error_for_unknown_alert(self):
        ctx = make_tool_context()
        result = await get_fraud_alert("FA-999", ctx)
        assert result["found"] is False

    @pytest.mark.asyncio
    async def test_stores_alert_data_in_state(self):
        ctx = make_tool_context()
        await get_fraud_alert("FA-001", ctx)
        assert ctx.state["alert_data"]["alert_id"] == "FA-001"

    @pytest.mark.asyncio
    async def test_stores_account_id_in_state(self):
        ctx = make_tool_context()
        await get_fraud_alert("FA-001", ctx)
        assert ctx.state["account_id"] == "ACCT-1001"

    @pytest.mark.asyncio
    async def test_all_known_alerts_return_found(self):
        for alert_id in ["FA-001", "FA-002", "FA-003", "FA-004"]:
            ctx = make_tool_context()
            result = await get_fraud_alert(alert_id, ctx)
            assert result["found"] is True


class TestGetAccountTransactions:
    @pytest.mark.asyncio
    async def test_returns_transactions_for_known_account(self):
        ctx = make_tool_context()
        result = await get_account_transactions("ACCT-1001", 30, ctx)
        assert result["account_id"] == "ACCT-1001"
        assert len(result["transactions"]) > 0

    @pytest.mark.asyncio
    async def test_returns_empty_for_unknown_account(self):
        ctx = make_tool_context()
        result = await get_account_transactions("ACCT-UNKNOWN", 30, ctx)
        assert result["summary"]["total_transactions"] == 0

    @pytest.mark.asyncio
    async def test_stores_transaction_data_in_state(self):
        ctx = make_tool_context()
        await get_account_transactions("ACCT-1001", 30, ctx)
        assert "transaction_data" in ctx.state

    @pytest.mark.asyncio
    async def test_summary_fields_present(self):
        ctx = make_tool_context()
        result = await get_account_transactions("ACCT-1001", 30, ctx)
        summary = result["summary"]
        assert "total_transactions" in summary
        assert "flagged_count" in summary
        assert "total_amount" in summary


class TestCheckDeviceFingerprint:
    @pytest.mark.asyncio
    async def test_returns_data_for_known_account(self):
        ctx = make_tool_context()
        result = await check_device_fingerprint("ACCT-1001", ctx)
        assert result["account_id"] == "ACCT-1001"
        assert len(result["known_devices"]) > 0

    @pytest.mark.asyncio
    async def test_returns_unknown_account_indicator(self):
        ctx = make_tool_context()
        result = await check_device_fingerprint("ACCT-UNKNOWN", ctx)
        assert "unknown_account" in result["risk_indicators"]

    @pytest.mark.asyncio
    async def test_stores_device_data_in_state(self):
        ctx = make_tool_context()
        await check_device_fingerprint("ACCT-1001", ctx)
        assert "device_data" in ctx.state

    @pytest.mark.asyncio
    async def test_high_risk_account_has_risk_indicators(self):
        ctx = make_tool_context()
        result = await check_device_fingerprint("ACCT-1001", ctx)
        assert len(result["risk_indicators"]) > 0


class TestFlagAccount:
    @pytest.mark.asyncio
    async def test_returns_case_number(self):
        ctx = make_tool_context()
        result = await flag_account("ACCT-1001", "fraud confirmed", "freeze", ctx)
        assert "case_number" in result
        assert result["case_number"].startswith("FRAUD-")

    @pytest.mark.asyncio
    async def test_status_is_account_flagged(self):
        ctx = make_tool_context()
        result = await flag_account("ACCT-1001", "reason", "freeze", ctx)
        assert result["status"] == "account_flagged"

    @pytest.mark.asyncio
    async def test_stores_flag_in_state(self):
        ctx = make_tool_context()
        await flag_account("ACCT-1001", "reason", "freeze", ctx)
        assert ctx.state["account_flagged"] is True

    @pytest.mark.asyncio
    async def test_stores_fraud_case_number_in_state(self):
        ctx = make_tool_context()
        await flag_account("ACCT-1001", "reason", "freeze", ctx)
        assert ctx.state["fraud_case_number"].startswith("FRAUD-")


class TestSubmitSar:
    @pytest.mark.asyncio
    async def test_returns_sar_id(self):
        ctx = make_tool_context()
        result = await submit_sar("ACCT-1001", "FA-001", "findings summary", ctx)
        assert "sar_id" in result
        assert result["sar_id"].startswith("SAR-")

    @pytest.mark.asyncio
    async def test_status_is_submitted(self):
        ctx = make_tool_context()
        result = await submit_sar("ACCT-1001", "FA-001", "findings", ctx)
        assert result["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_stores_sar_submitted_in_state(self):
        ctx = make_tool_context()
        await submit_sar("ACCT-1001", "FA-001", "findings", ctx)
        assert ctx.state["sar_submitted"] is True

    @pytest.mark.asyncio
    async def test_has_review_deadline(self):
        ctx = make_tool_context()
        result = await submit_sar("ACCT-1001", "FA-001", "findings", ctx)
        assert "review_deadline" in result


class TestCloseAlert:
    @pytest.mark.asyncio
    async def test_returns_alert_id(self):
        ctx = make_tool_context()
        result = await close_alert("FA-001", "false_positive", ctx)
        assert result["alert_id"] == "FA-001"

    @pytest.mark.asyncio
    async def test_status_is_closed(self):
        ctx = make_tool_context()
        result = await close_alert("FA-001", "confirmed_fraud", ctx)
        assert result["status"] == "closed"

    @pytest.mark.asyncio
    async def test_stores_alert_status_in_state(self):
        ctx = make_tool_context()
        await close_alert("FA-001", "false_positive", ctx)
        assert ctx.state["alert_status"] == "closed"

    @pytest.mark.asyncio
    async def test_stores_resolution_in_state(self):
        ctx = make_tool_context()
        await close_alert("FA-001", "false_positive", ctx)
        assert ctx.state["alert_resolution"] == "false_positive"


# ---------------------------------------------------------------------------
# Common tools
# ---------------------------------------------------------------------------

from workflow_engine.tools.common_tools import (
    add_case_note,
    escalate_to_supervisor,
    get_knowledge_article,
)


class TestEscalateToSupervisor:
    @pytest.mark.asyncio
    async def test_returns_escalation_id(self):
        ctx = make_tool_context()
        result = await escalate_to_supervisor("CASE-001", "customer upset", "high", ctx)
        assert result["escalation_id"].startswith("ESC-")

    @pytest.mark.asyncio
    async def test_status_is_escalated(self):
        ctx = make_tool_context()
        result = await escalate_to_supervisor("CASE-001", "reason", "high", ctx)
        assert result["status"] == "escalated"

    @pytest.mark.asyncio
    async def test_high_priority_fast_response(self):
        ctx = make_tool_context()
        result = await escalate_to_supervisor("CASE-001", "reason", "high", ctx)
        assert "2 hours" in result["estimated_response"]

    @pytest.mark.asyncio
    async def test_low_priority_slow_response(self):
        ctx = make_tool_context()
        result = await escalate_to_supervisor("CASE-001", "reason", "low", ctx)
        assert "24 hours" in result["estimated_response"]

    @pytest.mark.asyncio
    async def test_stores_workflow_status_in_state(self):
        ctx = make_tool_context()
        await escalate_to_supervisor("CASE-001", "reason", "medium", ctx)
        assert ctx.state["workflow_status"] == "escalated"


class TestAddCaseNote:
    @pytest.mark.asyncio
    async def test_returns_note_id(self):
        ctx = make_tool_context()
        result = await add_case_note("CASE-001", "note content", ctx)
        assert result["note_id"].startswith("NOTE-")

    @pytest.mark.asyncio
    async def test_appends_to_existing_notes(self):
        ctx = make_tool_context()
        await add_case_note("CASE-001", "first note", ctx)
        await add_case_note("CASE-001", "second note", ctx)
        assert len(ctx.state["case_notes"]) == 2

    @pytest.mark.asyncio
    async def test_creates_notes_list_if_absent(self):
        ctx = make_tool_context()
        await add_case_note("CASE-001", "note", ctx)
        assert isinstance(ctx.state["case_notes"], list)

    @pytest.mark.asyncio
    async def test_note_content_preserved(self):
        ctx = make_tool_context()
        await add_case_note("CASE-001", "important detail", ctx)
        assert ctx.state["case_notes"][0]["note"] == "important detail"


class TestGetKnowledgeArticle:
    @pytest.mark.asyncio
    async def test_returns_articles_list(self):
        ctx = make_tool_context()
        result = await get_knowledge_article("refund policy", ctx)
        assert "articles" in result
        assert isinstance(result["articles"], list)

    @pytest.mark.asyncio
    async def test_returns_matched_articles_for_refund_query(self):
        ctx = make_tool_context()
        result = await get_knowledge_article("refund", ctx)
        titles = [a["title"] for a in result["articles"]]
        assert any("Refund" in t for t in titles)

    @pytest.mark.asyncio
    async def test_fallback_returns_articles_for_unknown_query(self):
        ctx = make_tool_context()
        result = await get_knowledge_article("xyzzy_unknown_term", ctx)
        assert len(result["articles"]) > 0

    @pytest.mark.asyncio
    async def test_total_results_matches_articles_length(self):
        ctx = make_tool_context()
        result = await get_knowledge_article("escalation", ctx)
        assert result["total_results"] == len(result["articles"])

    @pytest.mark.asyncio
    async def test_query_preserved_in_result(self):
        ctx = make_tool_context()
        result = await get_knowledge_article("fraud investigation", ctx)
        assert result["query"] == "fraud investigation"
