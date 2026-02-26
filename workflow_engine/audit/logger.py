"""Immutable audit trail logger for compliance-critical actions.

Every financial action (refund, account flag, SAR submission, escalation)
is recorded with full context for regulatory compliance and forensic analysis.
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from ..logging_config import get_logger, correlation_id_var

logger = get_logger("audit")


class AuditAction(str, Enum):
    """Auditable actions in the system."""
    # Customer service
    ORDER_LOOKUP = "order.lookup"
    ORDER_SEARCH = "order.search"
    REFUND_ISSUED = "refund.issued"
    CASE_UPDATED = "case.updated"
    CASE_NOTE_ADDED = "case.note_added"

    # Fraud operations
    FRAUD_ALERT_VIEWED = "fraud_alert.viewed"
    TRANSACTIONS_VIEWED = "transactions.viewed"
    DEVICE_CHECK = "device.check"
    ACCOUNT_FLAGGED = "account.flagged"
    SAR_SUBMITTED = "sar.submitted"
    ALERT_CLOSED = "alert.closed"

    # Escalation
    ESCALATION_CREATED = "escalation.created"

    # Auth
    LOGIN = "auth.login"
    LOGIN_FAILED = "auth.login_failed"
    TOKEN_REFRESHED = "auth.token_refreshed"

    # Procedure engine
    PROCEDURE_STARTED = "procedure.started"
    PROCEDURE_COMPLETED = "procedure.completed"
    PROCEDURE_ESCALATED = "procedure.escalated"
    STEP_TRANSITION = "procedure.step_transition"

    # Session
    SESSION_CREATED = "session.created"


class AuditEntry:
    """A single audit trail entry."""

    def __init__(
        self,
        action: AuditAction,
        actor: str,
        resource_type: str,
        resource_id: str,
        session_id: Optional[str] = None,
        procedure_id: Optional[str] = None,
        step_id: Optional[str] = None,
        before_state: Optional[dict] = None,
        after_state: Optional[dict] = None,
        metadata: Optional[dict] = None,
    ):
        self.entry_id = str(uuid.uuid4())
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.correlation_id = correlation_id_var.get()
        self.action = action
        self.actor = actor
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.session_id = session_id
        self.procedure_id = procedure_id
        self.step_id = step_id
        self.before_state = before_state
        self.after_state = after_state
        self.metadata = metadata or {}

    def to_dict(self) -> dict[str, Any]:
        entry = {
            "entry_id": self.entry_id,
            "timestamp": self.timestamp,
            "action": self.action.value,
            "actor": self.actor,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
        }
        if self.correlation_id:
            entry["correlation_id"] = self.correlation_id
        if self.session_id:
            entry["session_id"] = self.session_id
        if self.procedure_id:
            entry["procedure_id"] = self.procedure_id
        if self.step_id:
            entry["step_id"] = self.step_id
        if self.before_state:
            entry["before_state"] = self.before_state
        if self.after_state:
            entry["after_state"] = self.after_state
        if self.metadata:
            entry["metadata"] = self.metadata
        return entry


class AuditLogger:
    """Audit logger that writes immutable audit trail entries.

    Entries are written to both the structured log and the database
    audit_trail table for compliance retention.
    """

    def __init__(self, db_write_func=None):
        """Initialize audit logger.

        Args:
            db_write_func: Optional async function to persist entries to database.
                           Signature: async def write(entry: dict) -> None
        """
        self._db_write = db_write_func

    async def log(
        self,
        action: AuditAction,
        actor: str,
        resource_type: str,
        resource_id: str,
        session_id: Optional[str] = None,
        procedure_id: Optional[str] = None,
        step_id: Optional[str] = None,
        before_state: Optional[dict] = None,
        after_state: Optional[dict] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        """Record an audit trail entry.

        Returns:
            The audit entry ID.
        """
        entry = AuditEntry(
            action=action,
            actor=actor,
            resource_type=resource_type,
            resource_id=resource_id,
            session_id=session_id,
            procedure_id=procedure_id,
            step_id=step_id,
            before_state=before_state,
            after_state=after_state,
            metadata=metadata,
        )

        entry_dict = entry.to_dict()

        # Always log to structured logger
        logger.info("AUDIT: %s", entry.action.value, extra={"extra_data": entry_dict})

        # Persist to database if configured
        if self._db_write:
            try:
                await self._db_write(entry_dict)
            except Exception as e:
                logger.error("Failed to persist audit entry %s: %s", entry.entry_id, e)

        return entry.entry_id


# Module-level singleton (initialized with DB writer during app startup)
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """Get the global audit logger instance."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


def init_audit_logger(db_write_func=None) -> AuditLogger:
    """Initialize the global audit logger with a DB writer."""
    global _audit_logger
    _audit_logger = AuditLogger(db_write_func=db_write_func)
    return _audit_logger
