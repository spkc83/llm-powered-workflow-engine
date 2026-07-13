"""Model-facing proposal tools for consequential actions.

These functions deliberately do not execute or persist business effects.  They
place an untrusted intent in the ADK session state; trusted application code
later validates the intent and creates an immutable action proposal.  A host UI
or channel adapter must still capture confirmation before the typed gateway can
execute anything.
"""

from __future__ import annotations

from typing import Any

from google.adk.tools import ToolContext

from workflow_engine.tools.access import authorize_tool


def _queue(
    action: str,
    arguments: dict[str, Any],
    tool_context: ToolContext,
    *,
    resource_type: str | None = None,
    resource_id: str | None = None,
) -> dict[str, Any]:
    authorize_tool(action, tool_context)
    intents = list(tool_context.state.get("pending_action_intents", []))
    intent: dict[str, Any] = {"action": action, "arguments": arguments}
    if resource_type and resource_id:
        intent["resource"] = {
            "resource_type": resource_type,
            "resource_id": resource_id,
        }
    # Avoid repeated tool calls generating duplicate cards in one model turn.
    if intent not in intents:
        intents.append(intent)
    tool_context.state["pending_action_intents"] = intents
    return {
        "status": "confirmation_required",
        "action": action,
        "message": (
            "The action has been proposed but not executed. The application will "
            "show the customer or operator an authoritative confirmation card."
        ),
    }


async def issue_refund(order_id: str, reason: str, tool_context: ToolContext) -> dict:
    """Propose a refund; never execute it from the model tool call."""
    return _queue(
        "issue_refund",
        {"order_id": order_id, "reason": reason},
        tool_context,
        resource_type="order",
        resource_id=order_id,
    )


async def issue_store_credit(order_id: str, reason: str, tool_context: ToolContext) -> dict:
    """Propose store credit using an authoritative order reload."""
    return _queue(
        "issue_store_credit",
        {"order_id": order_id, "reason": reason},
        tool_context,
        resource_type="order",
        resource_id=order_id,
    )


async def update_case_status(
    case_id: str, status: str, notes: str, tool_context: ToolContext
) -> dict:
    """Propose a case status change."""
    return _queue(
        "update_case_status",
        {"case_id": case_id, "target_status": status, "reason": notes},
        tool_context,
    )


async def file_eft_dispute(
    customer_id: str,
    transaction_id: str,
    dispute_type: str,
    amount: float,
    merchant: str,
    transaction_date: str,
    reason: str,
    tool_context: ToolContext,
    account_id: str | None = None,
    payment_method: str = "debit_card",
) -> dict:
    """Propose an EFT dispute using a trusted transaction reload."""
    return _queue(
        "file_eft_dispute",
        {
            "customer_id": customer_id,
            "transaction_id": transaction_id,
            "amount": amount,
            "dispute_type": dispute_type,
            "merchant": merchant,
            "transaction_date": transaction_date,
            "reason": reason,
            "account_id": account_id,
            "payment_method": payment_method,
        },
        tool_context,
        resource_type="transaction",
        resource_id=transaction_id,
    )


async def issue_provisional_credit(
    dispute_id: str, tool_context: ToolContext
) -> dict:
    """Propose provisional credit using the current dispute context."""
    dispute = dict(tool_context.state.get("dispute_data", {}))
    return _queue(
        "issue_provisional_credit",
        {
            "customer_id": tool_context.state.get("customer_id"),
            "dispute_id": dispute_id,
            "amount": dispute.get("amount"),
        },
        tool_context,
        resource_type="dispute",
        resource_id=dispute_id,
    )


async def escalate_to_supervisor(
    case_id: str, reason: str, priority: str, tool_context: ToolContext
) -> dict:
    """Propose a supervisor escalation."""
    return _queue(
        "escalate_to_supervisor",
        {"case_id": case_id, "reason": reason, "priority": priority},
        tool_context,
    )


async def add_case_note(case_id: str, note: str, tool_context: ToolContext) -> dict:
    """Propose adding a case note."""
    return _queue(
        "add_case_note", {"case_id": case_id, "note": note}, tool_context
    )


async def flag_account(
    account_id: str, reason: str, action: str, tool_context: ToolContext
) -> dict:
    """Propose an account restriction."""
    return _queue(
        "flag_account",
        {"account_id": account_id, "reason": reason, "restriction": action},
        tool_context,
        resource_type="account",
        resource_id=account_id,
    )


async def submit_sar(
    account_id: str, alert_id: str, findings: str, tool_context: ToolContext
) -> dict:
    """Propose SAR submission using a secure narrative reference."""
    return _queue(
        "submit_sar",
        {
            "account_id": account_id,
            "alert_id": alert_id,
            "narrative_ref": f"conversation-state:{alert_id}:findings",
        },
        tool_context,
        resource_type="fraud_alert",
        resource_id=alert_id,
    )


async def close_alert(
    alert_id: str, resolution: str, tool_context: ToolContext
) -> dict:
    """Propose closing a fraud alert."""
    return _queue(
        "close_alert",
        {"alert_id": alert_id, "resolution": resolution},
        tool_context,
        resource_type="fraud_alert",
        resource_id=alert_id,
    )
