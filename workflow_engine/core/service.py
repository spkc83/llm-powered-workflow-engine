"""Application facade for deterministic vertical slices."""

from workflow_engine.core.domains import OrderSnapshot, RefundDecisionService
from workflow_engine.core.gateway import ActionGateway
from workflow_engine.core.kernel import (
    ActionCommand,
    ActionRecord,
    CaseKernel,
    FactAuthority,
    FactProposal,
)


class CoreEngine:
    def __init__(self, kernel: CaseKernel, gateway: ActionGateway, refund_policy: RefundDecisionService):
        self.kernel = kernel
        self.gateway = gateway
        self.refund_policy = refund_policy

    async def process_refund(
        self,
        *,
        case_id: str,
        authenticated_customer_id: str,
        actor_id: str,
        policy_package_id: str,
        procedure_version: str,
        order: OrderSnapshot,
        reason: str = "customer_request",
        consent_evidence_ref: str | None = None,
    ) -> ActionRecord:
        decision = self.refund_policy.evaluate(
            order_id=order.order_id,
            authenticated_customer_id=authenticated_customer_id,
            order_customer_id=order.customer_id,
            order_status=order.status,
            days_since_delivery=order.days_since_delivery,
            amount=order.amount,
        )
        if not decision.eligible:
            raise ValueError(f"Refund is not eligible: {decision.reason}")

        existing_action = await self.kernel.store.get_action_by_key(decision.idempotency_key)
        if existing_action is not None:
            return await self.gateway.dispatch(existing_action)

        case = await self.kernel.store.get_case(case_id)
        if case is None:
            case = await self.kernel.create_case(
                case_id, authenticated_customer_id, "cs_refund", procedure_version
            )
        case = await self.kernel.commit_fact(
            case_id,
            FactProposal(
                name="order_id", value=order.order_id, authority=FactAuthority.VERIFIED,
                source="orders_db", evidence_ref=order.evidence_ref,
            ),
            case.version,
        )
        case = await self.kernel.commit_fact(
            case_id,
            FactProposal(
                name="customer_id", value=authenticated_customer_id,
                authority=FactAuthority.VERIFIED, source="authenticated_context",
                evidence_ref=f"actor-customer-binding:{authenticated_customer_id}",
            ),
            case.version,
        )
        case = await self.kernel.commit_fact(
            case_id,
            FactProposal(
                name="refund_amount", value=order.amount, authority=FactAuthority.VERIFIED,
                source="orders_db", evidence_ref=order.evidence_ref,
            ),
            case.version,
        )
        command = ActionCommand(
            action="issue_refund", case_id=case_id, policy_package_id=policy_package_id,
            actor_id=actor_id, idempotency_key=decision.idempotency_key,
            parameters={
                "order_id": order.order_id, "refund_amount": order.amount,
                "customer_id": authenticated_customer_id, "reason": reason,
            },
            parameter_fact_refs={
                "order_id": "order_id", "refund_amount": "refund_amount",
                "customer_id": "customer_id",
            },
            required_fact_authority={
                "order_id": FactAuthority.VERIFIED,
                "refund_amount": FactAuthority.VERIFIED,
                "customer_id": FactAuthority.VERIFIED,
            },
            consent_evidence_ref=consent_evidence_ref,
        )
        authorized = await self.kernel.authorize_action(command, case.version)
        return await self.gateway.dispatch(authorized)
