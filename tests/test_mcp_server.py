import json

import pytest
from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError

from workflow_engine.actions import ActionIntent, TrustedActionContext
from workflow_engine.core.kernel import ActionProposal, ActionProposalStatus
from workflow_engine.mcp import create_action_mcp_server


def _proposal(status=ActionProposalStatus.PENDING, action_id=None):
    return ActionProposal(
        proposal_id="APR-MCP-1",
        action="issue_refund",
        payload={"action": "issue_refund", "order_id": "ORD-123"},
        case_id="CASE-1",
        customer_id="CUST-456",
        actor_id="integration-agent",
        procedure_id="cs_refund",
        procedure_version="1.0.0",
        policy_package_id="refund@1.0.0:NAM",
        idempotency_key="refund:ORD-123",
        resource_type="order",
        resource_id="ORD-123",
        resource_version=1,
        conversation_id="CONV-1",
        message_id="MSG-1",
        preview={"order_id": "ORD-123", "amount": 79.99, "currency": "USD"},
        status=status,
        action_id=action_id,
        created_at="2026-07-13T00:00:00+00:00",
        expires_at="2026-07-13T01:00:00+00:00",
        updated_at="2026-07-13T00:00:00+00:00",
    )


class FakeBridge:
    def __init__(self):
        self.propose_calls = []
        self.status_calls = []

    async def propose(self, intent: ActionIntent, *, context: TrustedActionContext):
        self.propose_calls.append((intent, context))
        return _proposal()

    async def status(
        self, proposal_id: str, *, customer_id: str, actor_id: str | None = None
    ):
        self.status_calls.append((proposal_id, customer_id, actor_id))
        return _proposal(ActionProposalStatus.CONFIRMED, "ACT-1")


class FakeResolver:
    def __init__(self):
        self.contexts = []

    async def __call__(
        self,
        context: Context,
        action: str | None = None,
        arguments: dict | None = None,
    ) -> TrustedActionContext:
        self.contexts.append((context, action, arguments))
        return TrustedActionContext(
            actor_id="integration-agent",
            customer_id="CUST-456",
            case_id="CASE-1",
            procedure_id="cs_refund",
            procedure_version="1.0.0",
            policy_package_id="refund@1.0.0:NAM",
            conversation_id="CONV-1",
            message_id="MSG-1",
        )


@pytest.mark.asyncio
async def test_mcp_surface_is_proposal_only_and_has_no_trusted_arguments():
    server = create_action_mcp_server(FakeBridge(), FakeResolver())

    tools = await server.list_tools()
    assert {tool.name for tool in tools} == {"actions_prepare", "actions_get_status"}
    assert not any(
        word in tool.name for tool in tools for word in ("confirm", "execute", "dispatch")
    )

    forbidden = {
        "actor_id",
        "customer_id",
        "case_id",
        "procedure_id",
        "procedure_version",
        "policy_package_id",
        "idempotency_key",
        "consent_evidence_ref",
        "approval_evidence_ref",
        "provider_url",
        "base_url",
        "connector_binding_id",
    }
    for tool in tools:
        properties = set(tool.inputSchema.get("properties", {}))
        assert properties.isdisjoint(forbidden)
    prepare = next(tool for tool in tools if tool.name == "actions_prepare")
    assert set(prepare.inputSchema["properties"]) == {
        "action",
        "arguments",
        "resource_type",
        "resource_id",
    }


@pytest.mark.asyncio
async def test_mcp_tools_use_resolved_context_and_return_only_safe_fields():
    bridge = FakeBridge()
    resolver = FakeResolver()
    server = create_action_mcp_server(bridge, resolver)
    request_context = Context()

    prepared = await server._tool_manager.call_tool(
        "actions_prepare",
        {
            "action": "issue_refund",
            "arguments": {"order_id": "ORD-123", "reason": "customer request"},
            "resource_type": "order",
            "resource_id": "ORD-123",
        },
        context=request_context,
    )
    status = await server._tool_manager.call_tool(
        "actions_get_status",
        {"proposal_id": "APR-MCP-1"},
        context=request_context,
    )

    assert prepared == {
        "proposal_id": "APR-MCP-1",
        "action": "issue_refund",
        "preview": {"order_id": "ORD-123", "amount": 79.99, "currency": "USD"},
        "status": "pending",
        "expires_at": "2026-07-13T01:00:00+00:00",
        "action_id": None,
    }
    assert status["status"] == "confirmed"
    assert status["action_id"] == "ACT-1"
    assert bridge.propose_calls[0][1].actor_id == "integration-agent"
    assert bridge.status_calls == [
        ("APR-MCP-1", "CUST-456", "integration-agent")
    ]
    assert resolver.contexts == [
        (
            request_context,
            "issue_refund",
            {"order_id": "ORD-123", "reason": "customer request"},
        ),
        (request_context, None, None),
    ]
    assert "policy_package_id" not in prepared
    assert "customer_id" not in prepared


@pytest.mark.asyncio
async def test_mcp_prepare_rejects_trusted_fields_hidden_inside_arguments():
    server = create_action_mcp_server(FakeBridge(), FakeResolver())

    with pytest.raises(ToolError, match="Trusted action context"):
        await server._tool_manager.call_tool(
            "actions_prepare",
            {
                "action": "issue_refund",
                "arguments": {
                    "order_id": "ORD-123",
                    "actor_id": "attacker-selected-actor",
                    "provider_url": "https://attacker.invalid",
                },
            },
            context=Context(),
        )


@pytest.mark.asyncio
async def test_mcp_lists_read_only_resources_and_guidance_prompts():
    server = create_action_mcp_server(FakeBridge(), FakeResolver())

    resources = await server.list_resources()
    templates = await server.list_resource_templates()
    prompts = await server.list_prompts()

    assert {(str(resource.uri), resource.name) for resource in resources} == {
        ("actions://catalog", "actions_catalog")
    }
    assert {(template.uriTemplate, template.name) for template in templates} == {
        ("actions://proposals/{proposal_id}", "action_proposal_status")
    }
    assert {prompt.name for prompt in prompts} == {
        "actions_workflow",
        "actions_safety",
    }

    catalog_contents = list(await server.read_resource("actions://catalog"))
    catalog = json.loads(catalog_contents[0].content)
    assert "issue_refund" in {action["name"] for action in catalog["actions"]}
    assert not any("url" in key for action in catalog["actions"] for key in action)


def test_mcp_factory_is_streamable_http_compatible_and_stateless():
    server = create_action_mcp_server(FakeBridge(), FakeResolver())

    assert server.settings.stateless_http is True
    assert server.settings.json_response is True
    assert server.settings.streamable_http_path == "/"
    app = server.streamable_http_app()
    assert any(getattr(route, "path", None) == "/" for route in app.routes)
