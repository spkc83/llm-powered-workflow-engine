"""Domain connector adapters used only behind the action gateway."""

import hashlib
from datetime import datetime, timezone

from workflow_engine.core.domains import RefundDecisionService
from workflow_engine.core.gateway import ConnectorOutcome
from workflow_engine.database.repository import OrderRepository, RefundRepository


class DatabaseRefundConnector:
    """Transactionally revalidates refund inputs before recording the effect."""

    async def dispatch(self, command) -> ConnectorOutcome:
        order_id = command.parameters["order_id"]
        order = await OrderRepository.get_by_id(order_id)
        if order is None:
            return ConnectorOutcome.failed({"reason": "order_not_found"})
        customer_id = command.parameters["customer_id"]
        decision = RefundDecisionService().evaluate(
            order_id=order_id,
            authenticated_customer_id=customer_id,
            order_customer_id=order["customer_id"],
            order_status=order["status"],
            days_since_delivery=order["days_since_delivery"] or 0,
            amount=order["total"],
        )
        if not decision.eligible:
            return ConnectorOutcome.failed({"reason": decision.reason})
        if float(command.parameters["refund_amount"]) != float(order["total"]):
            return ConnectorOutcome.failed({"reason": "amount_changed"})

        existing = await RefundRepository.get_by_order(order_id)
        if existing:
            return ConnectorOutcome.succeeded(existing)

        refund_id = "REF-" + hashlib.sha256(command.idempotency_key.encode()).hexdigest()[:16].upper()
        processed_at = datetime.now(timezone.utc).isoformat()
        await RefundRepository.create(
            refund_id=refund_id,
            order_id=order_id,
            amount=order["total"],
            reason=command.parameters["reason"],
            refund_method=order["payment_method"] or "original_payment_method",
            processed_at=processed_at,
        )
        return ConnectorOutcome.succeeded(
            {
                "refund_id": refund_id, "order_id": order_id, "amount": order["total"],
                "currency": "USD", "status": "processed", "processed_at": processed_at,
            }
        )

    async def reconcile(self, command, prior) -> ConnectorOutcome:
        refund = await RefundRepository.get_by_order(command.parameters["order_id"])
        if refund:
            return ConnectorOutcome.succeeded(refund)
        return ConnectorOutcome.unknown(prior or {"reason": "provider_outcome_unresolved"})
