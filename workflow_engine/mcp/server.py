"""FastMCP facade for proposing actions without granting execution authority."""

from __future__ import annotations

import json
from typing import Annotated, Any, Protocol

from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field

from workflow_engine.actions import ActionBridge, ActionIntent, TrustedActionContext
from workflow_engine.core.action_specs import ACTION_SPECIFICATIONS
from workflow_engine.core.kernel import ActionProposal


_TRUSTED_ARGUMENT_NAMES = frozenset(
    {
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
        "connector_binding_version",
        "contract_version",
    }
)


class TrustedContextResolver(Protocol):
    """Resolve server-owned identity and policy context from an MCP request."""

    async def __call__(
        self,
        context: Context,
        action: str | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> TrustedActionContext: ...


def _safe_proposal(proposal: ActionProposal) -> dict[str, Any]:
    """Return only model-safe proposal state, never trusted authorization inputs."""
    status: str = (
        proposal.status.value
        if hasattr(proposal.status, "value")
        else str(proposal.status)
    )
    return {
        "proposal_id": proposal.proposal_id,
        "action": proposal.action,
        "preview": proposal.preview,
        "status": status,
        "expires_at": proposal.expires_at,
        "action_id": proposal.action_id,
    }


def _catalog() -> dict[str, Any]:
    actions = []
    for name, specification in sorted(ACTION_SPECIFICATIONS.items()):
        actions.append(
            {
                "name": name,
                "required_arguments": sorted(specification.required_parameters),
                "authoritative_arguments": sorted(
                    specification.authoritative_parameters
                ),
                "requires_customer_confirmation": specification.requires_consent,
                "requires_host_approval": specification.requires_approval,
            }
        )
    return {"actions": actions}


def _reject_trusted_arguments(arguments: dict[str, Any]) -> None:
    rejected = _TRUSTED_ARGUMENT_NAMES.intersection(arguments)
    if rejected:
        raise ValueError(
            "Trusted action context cannot be supplied through MCP arguments: "
            + ", ".join(sorted(rejected))
        )


def create_action_mcp_server(
    bridge: ActionBridge,
    context_resolver: TrustedContextResolver,
    *,
    name: str = "workflow-engine-actions",
) -> FastMCP:
    """Create a Streamable HTTP-compatible, proposal-only MCP server.

    The returned server is stateless at the HTTP transport layer. Durable proposal
    and action state remains in the injected bridge/core store. Host applications
    own authentication and inject a resolver that derives trusted identity and
    policy context from ``Context.request_context``.
    """

    server = FastMCP(
        name,
        instructions=(
            "This server may prepare consequential-action proposals and read their "
            "status. It cannot confirm, execute, approve, or configure providers. "
            "A trusted host must obtain customer confirmation and execute through "
            "the typed action gateway."
        ),
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
    )

    @server.tool(
        name="actions_prepare",
        description=(
            "Prepare a typed action proposal for host review. This never confirms "
            "or executes the action. Identity, policy, evidence, idempotency, and "
            "provider binding are derived by trusted server code."
        ),
        structured_output=True,
    )
    async def actions_prepare(
        action: Annotated[
            str,
            Field(description="Action name from the read-only actions catalog"),
        ],
        arguments: Annotated[
            dict[str, Any],
            Field(description="Model-suggested business arguments only"),
        ],
        context: Context,
        resource_type: Annotated[
            str | None,
            Field(description="Optional authoritative resource kind"),
        ] = None,
        resource_id: Annotated[
            str | None,
            Field(description="Optional authoritative resource identifier"),
        ] = None,
    ) -> dict[str, Any]:
        _reject_trusted_arguments(arguments)
        trusted = await context_resolver(context, action, arguments)
        proposal = await bridge.propose(
            ActionIntent(
                action=action,
                arguments=arguments,
                resource_type=resource_type,
                resource_id=resource_id,
            ),
            context=trusted,
        )
        return _safe_proposal(proposal)

    @server.tool(
        name="actions_get_status",
        description=(
            "Read the current status of an existing action proposal owned by the "
            "trusted customer context. This cannot change proposal or action state."
        ),
        structured_output=True,
    )
    async def actions_get_status(
        proposal_id: Annotated[
            str,
            Field(description="Proposal identifier returned by actions_prepare"),
        ],
        context: Context,
    ) -> dict[str, Any]:
        trusted = await context_resolver(context, None, None)
        proposal = await bridge.status(
            proposal_id,
            customer_id=trusted.customer_id,
            actor_id=trusted.actor_id,
        )
        return _safe_proposal(proposal)

    @server.resource(
        "actions://catalog",
        name="actions_catalog",
        description="Read-only closed catalog of proposal-capable action names.",
        mime_type="application/json",
    )
    async def actions_catalog() -> str:
        return json.dumps(_catalog(), sort_keys=True)

    @server.resource(
        "actions://proposals/{proposal_id}",
        name="action_proposal_status",
        description="Read-only status for a proposal in the trusted customer context.",
        mime_type="application/json",
    )
    async def action_proposal_status(proposal_id: str, context: Context) -> str:
        trusted = await context_resolver(context, None, None)
        proposal = await bridge.status(
            proposal_id,
            customer_id=trusted.customer_id,
            actor_id=trusted.actor_id,
        )
        return json.dumps(_safe_proposal(proposal), sort_keys=True, default=str)

    @server.prompt(
        name="actions_workflow",
        description="Guidance for safely proposing a consequential action.",
    )
    def actions_workflow() -> str:
        return (
            "Use actions://catalog to select a supported action. Gather only the "
            "business arguments needed for actions_prepare. Present its preview to "
            "the customer and ask the trusted host UI to collect confirmation. Never "
            "claim success from a pending or merely confirmed proposal; use "
            "actions_get_status for authoritative state."
        )

    @server.prompt(
        name="actions_safety",
        description="Non-bypassable boundaries for action-capable assistants.",
    )
    def actions_safety() -> str:
        return (
            "Never request or invent actor identity, customer identity, policy IDs, "
            "evidence references, idempotency keys, provider URLs, or credentials. "
            "This MCP facade cannot confirm or execute actions. Confirmation and "
            "delivery belong exclusively to the trusted host and typed action core."
        )

    return server
