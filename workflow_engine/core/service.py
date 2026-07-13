"""Application facade for deterministic vertical slices."""

from typing import Any

from workflow_engine.core.action_service import (
    AuthoritativeResourceRef,
    ConsequentialActionRequest,
    ConsequentialActionService,
)
from workflow_engine.core.domains import OrderSnapshot, RefundDecisionService
from workflow_engine.core.gateway import ActionGateway
from workflow_engine.core.kernel import ActionRecord, CaseKernel


class _SingleOrderResourceProvider:
    def __init__(self, order: OrderSnapshot):
        self.order = order

    async def get_resource(
        self, resource_type: str, resource_id: str
    ) -> dict[str, Any] | None:
        if resource_type != "order" or resource_id != self.order.order_id:
            return None
        return {
            "payload": {
                "order_id": self.order.order_id,
                "customer_id": self.order.customer_id,
                "status": self.order.status,
                "days_since_delivery": self.order.days_since_delivery,
                "amount": self.order.amount,
                "refund_amount": self.order.amount,
                "currency": "USD",
                "payment_method": self.order.payment_method,
            },
            "version": 1,
            "evidence_ref": self.order.evidence_ref,
        }


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

        service = ConsequentialActionService(
            self.kernel,
            self.gateway,
            _SingleOrderResourceProvider(order),
        )
        return await service.submit(
            ConsequentialActionRequest(
                case_id=case_id,
                customer_id=authenticated_customer_id,
                procedure_id="cs_refund",
                procedure_version=procedure_version,
                policy_package_id=policy_package_id,
                idempotency_key=decision.idempotency_key,
                resource=AuthoritativeResourceRef(
                    resource_type="order",
                    resource_id=order.order_id,
                ),
                payload={
                    "action": "issue_refund",
                    "order_id": order.order_id,
                    "customer_id": authenticated_customer_id,
                    "refund_amount": order.amount,
                    "currency": "USD",
                    "payment_method": order.payment_method,
                    "reason": reason,
                },
                consent_evidence_ref=consent_evidence_ref,
            ),
            actor_id=actor_id,
        )
