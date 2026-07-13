from unittest.mock import MagicMock

import pytest

from workflow_engine.auth.models import Permission
from workflow_engine.tools.action_proposals import issue_refund


@pytest.mark.asyncio
async def test_model_refund_tool_only_queues_intent() -> None:
    context = MagicMock()
    context.state = {
        "customer_id": "CUST-456",
        "actor_permissions": [Permission.REFUND_WRITE.value],
    }

    result = await issue_refund("ORD-123", "not received", context)

    assert result["status"] == "confirmation_required"
    assert "refund_id" not in result
    assert context.state["pending_action_intents"] == [
        {
            "action": "issue_refund",
            "arguments": {"order_id": "ORD-123", "reason": "not received"},
            "resource": {"resource_type": "order", "resource_id": "ORD-123"},
        }
    ]


@pytest.mark.asyncio
async def test_duplicate_model_proposal_is_collapsed_within_turn() -> None:
    context = MagicMock()
    context.state = {
        "customer_id": "CUST-456",
        "actor_permissions": [Permission.REFUND_WRITE.value],
    }

    await issue_refund("ORD-123", "not received", context)
    await issue_refund("ORD-123", "not received", context)

    assert len(context.state["pending_action_intents"]) == 1


@pytest.mark.asyncio
async def test_self_service_customer_may_propose_but_not_execute_refund() -> None:
    context = MagicMock()
    context.state = {
        "customer_id": "CUST-456",
        "actor_role": "customer",
        "actor_permissions": [],
    }

    result = await issue_refund("ORD-123", "not received", context)

    assert result["status"] == "confirmation_required"
    assert context.state["pending_action_intents"][0]["action"] == "issue_refund"
