"""Tests for the audit trail logger."""

import pytest

from workflow_engine.audit.logger import AuditAction, AuditEntry, AuditLogger


class TestAuditEntry:
    def test_creates_entry_with_required_fields(self):
        entry = AuditEntry(
            action=AuditAction.REFUND_ISSUED,
            actor="agent-1",
            resource_type="refund",
            resource_id="REF-001",
        )
        assert entry.entry_id is not None
        assert entry.timestamp is not None
        assert entry.action == AuditAction.REFUND_ISSUED

    def test_to_dict(self):
        entry = AuditEntry(
            action=AuditAction.ACCOUNT_FLAGGED,
            actor="analyst-1",
            resource_type="account",
            resource_id="ACCT-1001",
            session_id="s1",
            procedure_id="fraud_alert_triage",
            metadata={"reason": "suspicious"},
        )
        d = entry.to_dict()
        assert d["action"] == "account.flagged"
        assert d["actor"] == "analyst-1"
        assert d["session_id"] == "s1"
        assert d["metadata"]["reason"] == "suspicious"

    def test_optional_fields_omitted_when_none(self):
        entry = AuditEntry(
            action=AuditAction.ORDER_LOOKUP,
            actor="agent-1",
            resource_type="order",
            resource_id="ORD-123",
        )
        d = entry.to_dict()
        assert "session_id" not in d
        assert "before_state" not in d


class TestAuditLogger:
    @pytest.mark.asyncio
    async def test_log_returns_entry_id(self):
        logger = AuditLogger()
        entry_id = await logger.log(
            action=AuditAction.REFUND_ISSUED,
            actor="test-user",
            resource_type="refund",
            resource_id="REF-001",
        )
        assert entry_id is not None
        assert len(entry_id) > 0

    @pytest.mark.asyncio
    async def test_log_with_db_writer(self):
        written = []

        async def mock_writer(entry: dict):
            written.append(entry)

        logger = AuditLogger(db_write_func=mock_writer)
        await logger.log(
            action=AuditAction.ACCOUNT_FLAGGED,
            actor="analyst",
            resource_type="account",
            resource_id="ACCT-1001",
            metadata={"action": "freeze"},
        )
        assert len(written) == 1
        assert written[0]["action"] == "account.flagged"

    @pytest.mark.asyncio
    async def test_log_survives_db_failure(self):
        async def failing_writer(entry: dict):
            raise RuntimeError("DB down")

        logger = AuditLogger(db_write_func=failing_writer)
        # Should not raise — logs the error but continues
        entry_id = await logger.log(
            action=AuditAction.SAR_SUBMITTED,
            actor="analyst",
            resource_type="sar",
            resource_id="SAR-001",
        )
        assert entry_id is not None
