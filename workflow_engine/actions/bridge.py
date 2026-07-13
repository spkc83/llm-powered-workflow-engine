"""Trusted proposal bridge between conversation flows and action core."""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Field, TypeAdapter

from workflow_engine.core.action_service import (
    ActionPayload,
    AuthoritativeResourceRef,
    ConsequentialActionRequest,
    ConsequentialActionService,
)
from workflow_engine.core.action_specs import ACTION_SPECIFICATIONS
from workflow_engine.core.domains import RefundDecisionService
from workflow_engine.core.kernel import (
    ActionConflict,
    ActionProposal,
    ActionProposalStatus,
    ActionRecord,
    CaseKernel,
)


_ACTION_PAYLOAD_ADAPTER = TypeAdapter(ActionPayload)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expired(expires_at: str) -> bool:
    return datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc)


class ActionIntent(BaseModel):
    """Model-suggested action shape. It deliberately excludes trusted context."""

    action: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    resource_type: str | None = None
    resource_id: str | None = None


class TrustedActionContext(BaseModel):
    actor_id: str
    customer_id: str
    case_id: str
    procedure_id: str
    procedure_version: str
    policy_package_id: str
    conversation_id: str | None = None
    message_id: str | None = None
    connector_binding_id: str | None = None
    connector_binding_version: str | None = None
    contract_version: str | None = None


class ActionConfirmationContext(BaseModel):
    actor_id: str
    customer_id: str
    consent_evidence_ref: str | None = None
    approval_evidence_ref: str | None = None


class ActionBridge:
    """Host-trusted two-step bridge: propose first, confirm later.

    ADK/MCP/model callers may provide an ``ActionIntent``. Identity, policy,
    resource versions, connector binding, evidence, and idempotency are derived
    by trusted application code and persisted with the proposal.
    """

    def __init__(
        self,
        *,
        kernel: CaseKernel,
        action_service: ConsequentialActionService,
        resources,
        connector_resolver=None,
        refund_policy: RefundDecisionService | None = None,
        ttl_seconds: int = 900,
    ):
        self.kernel = kernel
        self.action_service = action_service
        self.resources = resources
        self.connector_resolver = connector_resolver
        self.refund_policy = refund_policy or RefundDecisionService()
        self.ttl_seconds = ttl_seconds

    async def propose(
        self, intent: ActionIntent, *, context: TrustedActionContext
    ) -> ActionProposal:
        if intent.action not in ACTION_SPECIFICATIONS:
            raise ValueError(f"Unknown consequential action: {intent.action}")
        if self.connector_resolver is not None:
            resolved = self.connector_resolver.resolve(intent.action)
            context = context.model_copy(
                update={
                    "connector_binding_id": resolved.binding_id,
                    "connector_binding_version": resolved.binding_version,
                    "contract_version": resolved.contract_version,
                }
            )
        resource_type = intent.resource_type
        resource_id = intent.resource_id
        payload: dict[str, Any]
        resource: dict[str, Any] | None
        preview: dict[str, Any]
        if intent.action == "issue_refund":
            payload, resource, preview, resource_type, resource_id = await self._prepare_refund(
                intent, context
            )
        else:
            payload, resource, preview = await self._prepare_generic(intent, context)
        now = datetime.now(timezone.utc)
        proposal = ActionProposal(
            proposal_id=f"APR-{uuid.uuid4().hex}",
            action=intent.action,
            payload=payload,
            case_id=context.case_id,
            customer_id=context.customer_id,
            actor_id=context.actor_id,
            procedure_id=context.procedure_id,
            procedure_version=context.procedure_version,
            policy_package_id=context.policy_package_id,
            idempotency_key=self._idempotency_key(intent.action, payload, context),
            resource_type=resource_type,
            resource_id=resource_id,
            resource_version=resource.get("version") if resource else None,
            conversation_id=context.conversation_id,
            message_id=context.message_id,
            connector_binding_id=context.connector_binding_id,
            connector_binding_version=context.connector_binding_version,
            contract_version=context.contract_version,
            preview=preview,
            status=ActionProposalStatus.PENDING,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=self.ttl_seconds)).isoformat(),
            updated_at=now.isoformat(),
        )
        return await self.kernel.store.create_action_proposal(proposal)

    async def confirm(
        self,
        proposal_id: str,
        *,
        context: ActionConfirmationContext,
    ) -> ActionProposal:
        proposal = await self._get_owned(
            proposal_id, context.customer_id, actor_id=context.actor_id
        )
        if proposal.status is ActionProposalStatus.CONFIRMED:
            return proposal
        if proposal.status is not ActionProposalStatus.PENDING:
            raise ValueError(f"Action proposal is {proposal.status.value}")
        if _expired(proposal.expires_at):
            return await self._expire(proposal)
        await self._verify_resource_version(proposal)
        self._verify_connector_binding(proposal)
        specification = ACTION_SPECIFICATIONS[proposal.action]
        if specification.requires_consent and not context.consent_evidence_ref:
            raise ValueError(f"Action {proposal.action} requires explicit consent evidence")
        if specification.requires_approval and not context.approval_evidence_ref:
            raise ValueError(f"Action {proposal.action} requires approval evidence")
        request = ConsequentialActionRequest(
            case_id=proposal.case_id,
            customer_id=proposal.customer_id,
            procedure_id=proposal.procedure_id,
            procedure_version=proposal.procedure_version,
            policy_package_id=proposal.policy_package_id,
            idempotency_key=proposal.idempotency_key,
            resource=(
                AuthoritativeResourceRef(
                    resource_type=proposal.resource_type,
                    resource_id=proposal.resource_id,
                )
                if proposal.resource_type and proposal.resource_id
                else None
            ),
            payload=proposal.payload,
            consent_evidence_ref=(
                context.consent_evidence_ref
                if specification.requires_consent
                else None
            ),
            approval_evidence_ref=(
                context.approval_evidence_ref
                if specification.requires_approval
                else None
            ),
            connector_binding_id=proposal.connector_binding_id,
            connector_binding_version=proposal.connector_binding_version,
            contract_version=proposal.contract_version,
        )
        action = await self.action_service.submit(request, actor_id=context.actor_id)
        try:
            return await self.kernel.store.transition_action_proposal(
                proposal_id,
                ActionProposalStatus.PENDING,
                ActionProposalStatus.CONFIRMED,
                confirmation_evidence_ref=(
                    context.consent_evidence_ref or context.approval_evidence_ref
                ),
                action_id=action.action_id,
            )
        except ActionConflict:
            current = await self._get_owned(proposal_id, context.customer_id)
            if current.status is ActionProposalStatus.CONFIRMED:
                return current
            raise

    async def cancel(
        self,
        proposal_id: str,
        *,
        context: ActionConfirmationContext,
    ) -> ActionProposal:
        proposal = await self._get_owned(
            proposal_id, context.customer_id, actor_id=context.actor_id
        )
        if proposal.status is ActionProposalStatus.CANCELLED:
            return proposal
        if proposal.status is not ActionProposalStatus.PENDING:
            raise ValueError(f"Action proposal is {proposal.status.value}")
        existing_action = await self.kernel.store.get_action_by_key(proposal.idempotency_key)
        if existing_action is not None:
            return await self._recover_confirmed(proposal, existing_action)
        return await self.kernel.store.transition_action_proposal(
            proposal_id,
            ActionProposalStatus.PENDING,
            ActionProposalStatus.CANCELLED,
        )

    async def status(
        self, proposal_id: str, *, customer_id: str, actor_id: str | None = None
    ) -> ActionProposal:
        proposal = await self._get_owned(proposal_id, customer_id, actor_id=actor_id)
        if proposal.status is ActionProposalStatus.PENDING and _expired(proposal.expires_at):
            return await self._expire(proposal)
        return proposal

    async def _get_owned(
        self, proposal_id: str, customer_id: str, *, actor_id: str | None = None
    ) -> ActionProposal:
        proposal = await self.kernel.store.get_action_proposal(proposal_id)
        if proposal is None:
            raise KeyError(proposal_id)
        if proposal.customer_id != customer_id:
            raise ValueError("Action proposal does not belong to this customer")
        if actor_id is not None and proposal.actor_id != actor_id:
            raise ValueError("Action proposal does not belong to this actor")
        return proposal

    async def _prepare_refund(
        self, intent: ActionIntent, context: TrustedActionContext
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str, str]:
        resource_type = intent.resource_type or "order"
        order_id = intent.resource_id or intent.arguments.get("order_id")
        if not order_id:
            raise ValueError("issue_refund requires an order_id")
        resource = await self._load_resource(resource_type, str(order_id))
        assert resource is not None
        payload = resource["payload"]
        decision = self.refund_policy.evaluate(
            order_id=str(payload["order_id"]),
            authenticated_customer_id=context.customer_id,
            order_customer_id=str(payload["customer_id"]),
            order_status=str(payload.get("status", "delivered")),
            days_since_delivery=int(payload.get("days_since_delivery", 0)),
            amount=float(payload.get("refund_amount", payload.get("amount", 0))),
        )
        if not decision.eligible:
            raise ValueError(f"Refund is not eligible: {decision.reason}")
        currency = str(payload.get("currency", "USD"))
        refund_payload: dict[str, Any] = {
            "action": "issue_refund",
            "order_id": str(payload["order_id"]),
            "customer_id": context.customer_id,
            "refund_amount": decision.amount,
            "currency": currency,
            "payment_method": str(payload["payment_method"]),
            "reason": str(intent.arguments.get("reason") or "customer_request"),
        }
        preview: dict[str, Any] = {
            "action": "issue_refund",
            "order_id": refund_payload["order_id"],
            "refund_amount": refund_payload["refund_amount"],
            "currency": currency,
            "payment_method": refund_payload["payment_method"],
            "reason": refund_payload["reason"],
        }
        return refund_payload, resource, preview, resource_type, str(order_id)

    async def _prepare_generic(
        self, intent: ActionIntent, context: TrustedActionContext
    ) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any]]:
        specification = ACTION_SPECIFICATIONS[intent.action]
        resource = await self._load_resource(intent.resource_type, intent.resource_id)
        payload = {"action": intent.action, **intent.arguments}
        if specification.authoritative_parameters:
            if resource is None:
                raise ValueError("This action requires an authoritative resource reference")
            upstream_payload = resource["payload"]
            binding = specification.customer_binding_parameter
            if binding is not None:
                if binding not in upstream_payload:
                    raise ValueError(
                        f"Authoritative resource is missing customer binding {binding}"
                    )
                if str(upstream_payload[binding]) != context.customer_id:
                    raise ValueError(
                        "Authoritative resource does not belong to the serviced customer"
                    )
            for parameter in sorted(specification.authoritative_parameters):
                if parameter not in upstream_payload:
                    raise ValueError(f"Authoritative resource is missing {parameter}")
                payload[parameter] = upstream_payload[parameter]
        validated = _ACTION_PAYLOAD_ADAPTER.validate_python(payload).model_dump(mode="json")
        return (
            validated,
            resource,
            {"action": intent.action, "parameters": validated},
        )

    async def _load_resource(
        self, resource_type: str | None, resource_id: str | None
    ) -> dict[str, Any] | None:
        if not resource_type and not resource_id:
            return None
        if not resource_type or not resource_id:
            raise ValueError("Both resource_type and resource_id are required")
        resource = await self.resources.get_resource(resource_type, resource_id)
        if resource is None:
            raise ValueError("Authoritative resource was not found")
        return resource

    async def _verify_resource_version(self, proposal: ActionProposal) -> None:
        if proposal.resource_type is None or proposal.resource_id is None:
            return
        resource = await self._load_resource(proposal.resource_type, proposal.resource_id)
        assert resource is not None
        if resource.get("version") != proposal.resource_version:
            raise ValueError("Authoritative resource version changed after proposal")

    def _verify_connector_binding(self, proposal: ActionProposal) -> None:
        if self.connector_resolver is None:
            return
        resolved = self.connector_resolver.resolve(proposal.action)
        current = (
            resolved.binding_id,
            resolved.binding_version,
            resolved.contract_version,
        )
        proposed = (
            proposal.connector_binding_id,
            proposal.connector_binding_version,
            proposal.contract_version,
        )
        if current != proposed:
            raise ValueError("Action connector binding changed after proposal")

    async def _expire(self, proposal: ActionProposal) -> ActionProposal:
        try:
            return await self.kernel.store.transition_action_proposal(
                proposal.proposal_id,
                ActionProposalStatus.PENDING,
                ActionProposalStatus.EXPIRED,
            )
        except ActionConflict:
            current = await self.kernel.store.get_action_proposal(proposal.proposal_id)
            assert current is not None
            return current

    async def _recover_confirmed(
        self, proposal: ActionProposal, action: ActionRecord
    ) -> ActionProposal:
        try:
            return await self.kernel.store.transition_action_proposal(
                proposal.proposal_id,
                ActionProposalStatus.PENDING,
                ActionProposalStatus.CONFIRMED,
                action_id=action.action_id,
            )
        except ActionConflict:
            current = await self.kernel.store.get_action_proposal(proposal.proposal_id)
            assert current is not None
            return current

    @staticmethod
    def _idempotency_key(
        action: str, payload: dict[str, Any], context: TrustedActionContext
    ) -> str:
        if action == "issue_refund":
            return f"refund:{payload['order_id']}"
        digest = hashlib.sha256(
            repr((action, context.case_id, context.customer_id, payload)).encode()
        ).hexdigest()[:24]
        return f"{action}:{digest}"
