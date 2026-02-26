"""Common tools shared across agent domains.

Uses the repository pattern for data access and the audit logger
for compliance-critical actions (escalations, case notes).
"""

import uuid
from datetime import datetime

from google.adk.tools import ToolContext

from workflow_engine.audit import AuditAction, get_audit_logger
from workflow_engine.database.repository import (
    CaseRepository,
    EscalationRepository,
    KnowledgeRepository,
)
from workflow_engine.logging_config import get_logger

logger = get_logger("tools.common")


async def escalate_to_supervisor(case_id: str, reason: str, priority: str, tool_context: ToolContext) -> dict:
    """Escalate a case to a supervisor for further review.

    Args:
        case_id: The case ID to escalate.
        reason: Reason for escalation.
        priority: Priority level ("low", "medium", "high", "urgent").
    """
    now = datetime.now().isoformat()
    escalation_id = f"ESC-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    estimated_response = "within 2 hours" if priority in ("high", "urgent") else "within 24 hours"

    logger.info("Escalating case %s: priority=%s reason=%s", case_id, priority, reason)

    await EscalationRepository.create(
        escalation_id=escalation_id,
        case_id=case_id,
        reason=reason,
        priority=priority,
        assigned_to="Supervisor Martinez",
        estimated_response=estimated_response,
    )

    result = {
        "escalation_id": escalation_id,
        "case_id": case_id,
        "reason": reason,
        "priority": priority,
        "assigned_to": "Supervisor Martinez",
        "estimated_response": estimated_response,
        "escalated_at": now,
        "status": "escalated",
    }

    tool_context.state["escalation_data"] = result
    tool_context.state["workflow_status"] = "escalated"

    # Audit — compliance-critical
    audit = get_audit_logger()
    await audit.log(
        action=AuditAction.ESCALATION_CREATED,
        actor=tool_context.state.get("customer_id", "system"),
        resource_type="escalation",
        resource_id=escalation_id,
        session_id=str(getattr(tool_context, "session_id", None)),
        metadata={
            "case_id": case_id,
            "priority": priority,
            "reason": reason,
            "assigned_to": "Supervisor Martinez",
        },
    )

    return result


async def add_case_note(case_id: str, note: str, tool_context: ToolContext) -> dict:
    """Add a note to a case file.

    Args:
        case_id: The case ID to add a note to.
        note: The note content to add.
    """
    now = datetime.now().isoformat()
    note_id = f"NOTE-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

    logger.info("Adding note %s to case %s", note_id, case_id)

    await CaseRepository.add_note(note_id=note_id, case_id=case_id, note=note)

    result = {
        "note_id": note_id,
        "case_id": case_id,
        "note": note,
        "created_at": now,
        "created_by": "system",
    }

    existing_notes = tool_context.state.get("case_notes", [])
    existing_notes.append(result)
    tool_context.state["case_notes"] = existing_notes

    # Audit
    audit = get_audit_logger()
    await audit.log(
        action=AuditAction.CASE_NOTE_ADDED,
        actor=tool_context.state.get("customer_id", "system"),
        resource_type="case_note",
        resource_id=note_id,
        session_id=str(getattr(tool_context, "session_id", None)),
        metadata={"case_id": case_id, "note_length": len(note)},
    )

    return result


async def get_knowledge_article(query: str, tool_context: ToolContext) -> dict:
    """Search the knowledge base for relevant articles.

    Args:
        query: Search query for finding relevant knowledge articles.
    """
    logger.info("Knowledge base search: %s", query)

    matched = await KnowledgeRepository.search(query)

    return {"query": query, "articles": matched, "total_results": len(matched)}
