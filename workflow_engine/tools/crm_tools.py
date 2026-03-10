"""CRM tools for customer service operations.

Uses the repository pattern for data access and the audit logger
for compliance-critical actions.
"""

from datetime import datetime
from typing import Optional

from google.adk.tools import ToolContext

from workflow_engine.audit import AuditAction, get_audit_logger
from workflow_engine.database.repository import (
    CustomerRepository,
    OrderRepository,
    RefundRepository,
)
from workflow_engine.logging_config import get_logger

logger = get_logger("tools.crm")


async def lookup_order(order_id: str, tool_context: ToolContext) -> dict:
    """Look up an order by its order ID and return order details.

    Args:
        order_id: The order ID to look up (e.g., "ORD-123").
    """
    logger.info("Looking up order: %s", order_id)

    order = await OrderRepository.get_by_id(order_id)
    if order is None:
        return {"error": f"Order {order_id} not found", "found": False}

    # Verify the order belongs to the current customer
    session_customer_id = tool_context.state.get("customer_id")
    if session_customer_id and order["customer_id"] != session_customer_id:
        logger.warning(
            "Customer %s attempted to access order %s belonging to %s",
            session_customer_id, order_id, order["customer_id"],
        )
        return {"error": f"Order {order_id} not found", "found": False}

    items = await OrderRepository.get_items(order_id)

    # Compute days_since_delivery dynamically
    days_since_delivery = order["days_since_delivery"] or 0
    if order["delivery_date"]:
        try:
            delivery_dt = datetime.fromisoformat(order["delivery_date"])
            days_since_delivery = (datetime.now() - delivery_dt).days
        except (ValueError, TypeError):
            pass

    result = {
        "order_id": order["order_id"],
        "customer_name": order["customer_name"],
        "customer_id": order["customer_id"],
        "email": order["email"],
        "merchant_name": order["merchant_name"],
        "items": items,
        "total": order["total"],
        "status": order["status"],
        "order_date": order["order_date"],
        "delivery_date": order["delivery_date"],
        "days_since_delivery": days_since_delivery,
        "payment_method": order["payment_method"],
        "shipping_address": order["shipping_address"],
        "found": True,
    }

    tool_context.state["order_data"] = result
    tool_context.state["customer_id"] = order["customer_id"]

    # Audit
    audit = get_audit_logger()
    await audit.log(
        action=AuditAction.ORDER_LOOKUP,
        actor=tool_context.state.get("customer_id", "system"),
        resource_type="order",
        resource_id=order_id,
        session_id=str(getattr(tool_context, "session_id", None)),
        metadata={"status": order["status"], "total": order["total"]},
    )

    return result


async def get_customer_profile(customer_id: str, tool_context: ToolContext) -> dict:
    """Look up a customer profile by customer ID.

    Args:
        customer_id: The customer ID to look up (e.g., "CUST-456").
    """
    logger.info("Looking up customer: %s", customer_id)

    profile = await CustomerRepository.get_by_id(customer_id)
    if profile is None:
        return {"error": f"Customer {customer_id} not found", "found": False}

    result = {**profile, "found": True}
    tool_context.state["customer_data"] = profile
    return result


async def issue_refund(order_id: str, reason: str, tool_context: ToolContext) -> dict:
    """Process a refund for a given order.

    Args:
        order_id: The order ID to refund.
        reason: The reason for the refund.
    """
    order_data = tool_context.state.get("order_data", {})
    amount = order_data.get("total", 0)
    payment_method = order_data.get("payment_method", "original_payment_method")

    refund_id = f"REF-{order_id.split('-')[1]}-{datetime.now().strftime('%H%M%S')}"
    processed_at = datetime.now().isoformat()

    logger.info("Issuing refund %s for order %s (amount=%.2f)", refund_id, order_id, amount)

    await RefundRepository.create(
        refund_id=refund_id,
        order_id=order_id,
        amount=amount,
        reason=reason,
        refund_method=payment_method,
        processed_at=processed_at,
    )

    result = {
        "refund_id": refund_id,
        "order_id": order_id,
        "amount": amount,
        "currency": "USD",
        "status": "processed",
        "reason": reason,
        "refund_method": payment_method,
        "estimated_days": "5-7 business days",
        "processed_at": processed_at,
    }

    tool_context.state["refund_data"] = result
    tool_context.state["workflow_status"] = "refund_processed"

    # Audit — compliance-critical
    audit = get_audit_logger()
    await audit.log(
        action=AuditAction.REFUND_ISSUED,
        actor=tool_context.state.get("customer_id", "system"),
        resource_type="refund",
        resource_id=refund_id,
        session_id=str(getattr(tool_context, "session_id", None)),
        metadata={
            "order_id": order_id,
            "amount": amount,
            "currency": "USD",
            "reason": reason,
            "refund_method": payment_method,
        },
    )

    return result


async def issue_store_credit(order_id: str, reason: str, tool_context: ToolContext) -> dict:
    """Issue store credit for a given order (e.g., when outside the refund window).

    Args:
        order_id: The order ID to issue store credit for.
        reason: The reason for issuing store credit.
    """
    order_data = tool_context.state.get("order_data", {})
    amount = order_data.get("total", 0)
    customer_id = tool_context.state.get("customer_id", "unknown")

    credit_id = f"SC-{order_id.split('-')[1]}-{datetime.now().strftime('%H%M%S')}"
    processed_at = datetime.now().isoformat()

    logger.info("Issuing store credit %s for order %s (amount=%.2f)", credit_id, order_id, amount)

    await RefundRepository.create(
        refund_id=credit_id,
        order_id=order_id,
        amount=amount,
        reason=reason,
        refund_method="store_credit",
        processed_at=processed_at,
    )

    result = {
        "credit_id": credit_id,
        "order_id": order_id,
        "amount": amount,
        "currency": "USD",
        "status": "applied",
        "reason": reason,
        "credit_method": "store_credit",
        "expires": "12 months",
        "processed_at": processed_at,
    }

    tool_context.state["store_credit_data"] = result
    tool_context.state["workflow_status"] = "store_credit_issued"

    # Audit — compliance-critical
    audit = get_audit_logger()
    await audit.log(
        action=AuditAction.STORE_CREDIT_ISSUED,
        actor=customer_id,
        resource_type="store_credit",
        resource_id=credit_id,
        session_id=str(getattr(tool_context, "session_id", None)),
        metadata={
            "order_id": order_id,
            "amount": amount,
            "currency": "USD",
            "reason": reason,
        },
    )

    return result


async def update_case_status(case_id: str, status: str, notes: str, tool_context: ToolContext) -> dict:
    """Update the status of a customer service case.

    Args:
        case_id: The case ID to update.
        status: New status (e.g., "resolved", "closed", "escalated").
        notes: Notes about the status update.
    """
    from workflow_engine.database.repository import CaseRepository

    logger.info("Updating case %s to status=%s", case_id, status)

    await CaseRepository.upsert(
        case_id=case_id,
        status=status,
        notes=notes,
        customer_id=tool_context.state.get("customer_id"),
    )

    now = datetime.now().isoformat()
    result = {
        "case_id": case_id,
        "status": status,
        "notes": notes,
        "updated_at": now,
        "updated_by": "system",
    }

    tool_context.state["case_status"] = status
    tool_context.state["workflow_status"] = status

    # Audit
    audit = get_audit_logger()
    await audit.log(
        action=AuditAction.CASE_UPDATED,
        actor=tool_context.state.get("customer_id", "system"),
        resource_type="case",
        resource_id=case_id,
        session_id=str(getattr(tool_context, "session_id", None)),
        after_state={"status": status},
        metadata={"notes": notes},
    )

    return result


async def search_orders(
    customer_id: str,
    tool_context: ToolContext,
    merchant_name: Optional[str] = None,
    amount: Optional[float] = None,
    date: Optional[str] = None,
) -> dict:
    """Search for orders by customer ID and optional filters (merchant name, amount, date).

    Use this tool when a customer describes a purchase using natural language instead of
    providing an exact order ID. You can pass ANY combination of the optional filters —
    even just one (e.g., only merchant_name) is enough to narrow the search.

    Args:
        customer_id: The customer ID to search orders for (required).
        merchant_name: Partial or full merchant/store name (e.g., "TechMart"). Case-insensitive partial match.
        amount: Approximate order total (e.g., 80.0 for "about $80"). Matches within ±10%.
        date: Approximate order date in ISO format (e.g., "2026-02-15"). Matches within ±3 days.
    """
    logger.info(
        "Searching orders for customer=%s merchant=%s amount=%s date=%s",
        customer_id, merchant_name, amount, date,
    )

    rows = await OrderRepository.search(
        customer_id=customer_id,
        merchant_name=merchant_name,
        amount=amount,
        date=date,
    )

    # Fallback: if date filter produced no results, retry without it.
    # Vague terms like "last month" can be off by weeks; merchant_name alone
    # is usually enough to identify the order.
    if not rows and date and (merchant_name or amount):
        logger.info("Date-filtered search returned 0 results; retrying without date")
        rows = await OrderRepository.search(
            customer_id=customer_id,
            merchant_name=merchant_name,
            amount=amount,
            date=None,
        )

    # Audit
    audit = get_audit_logger()
    await audit.log(
        action=AuditAction.ORDER_SEARCH,
        actor=customer_id,
        resource_type="order",
        resource_id=f"search:{customer_id}",
        session_id=str(getattr(tool_context, "session_id", None)),
        metadata={
            "merchant_name": merchant_name,
            "amount": amount,
            "date": date,
            "results_count": len(rows),
        },
    )

    if not rows:
        return {"matches": [], "count": 0, "message": "No orders found matching that description."}

    # Enrich each match with item summaries
    matches = []
    for row in rows:
        items = await OrderRepository.get_items(row["order_id"])
        items_summary = ", ".join(f"{it['name']} (x{it['qty']})" for it in items) if items else "no items"

        # Compute days_since_delivery dynamically
        days_since_delivery = row["days_since_delivery"] or 0
        if row["delivery_date"]:
            try:
                delivery_dt = datetime.fromisoformat(row["delivery_date"])
                days_since_delivery = (datetime.now() - delivery_dt).days
            except (ValueError, TypeError):
                pass

        matches.append({
            "order_id": row["order_id"],
            "merchant_name": row["merchant_name"],
            "total": row["total"],
            "status": row["status"],
            "order_date": row["order_date"],
            "delivery_date": row["delivery_date"],
            "days_since_delivery": days_since_delivery,
            "items_summary": items_summary,
        })

    result = {"matches": matches, "count": len(matches)}

    # If exactly one match, populate state like lookup_order does
    if len(matches) == 1:
        match = matches[0]
        order = await OrderRepository.get_by_id(match["order_id"])

        # Defense-in-depth: verify the order belongs to the requesting customer
        if order["customer_id"] != customer_id:
            logger.warning(
                "search_orders: order %s belongs to %s, not requesting customer %s",
                match["order_id"], order["customer_id"], customer_id,
            )
            return {"matches": [], "count": 0, "message": "No orders found matching that description."}

        items = await OrderRepository.get_items(match["order_id"])
        order_data = {
            "order_id": order["order_id"],
            "customer_name": order["customer_name"],
            "customer_id": order["customer_id"],
            "email": order["email"],
            "merchant_name": order["merchant_name"],
            "items": items,
            "total": order["total"],
            "status": order["status"],
            "order_date": order["order_date"],
            "delivery_date": order["delivery_date"],
            "days_since_delivery": match["days_since_delivery"],
            "payment_method": order["payment_method"],
            "shipping_address": order["shipping_address"],
            "found": True,
        }
        tool_context.state["order_data"] = order_data
        tool_context.state["customer_id"] = order["customer_id"]
        result["message"] = f"Found order {match['order_id']} from {match['merchant_name']}."
    else:
        result["message"] = f"Found {len(matches)} orders. Please ask the customer to confirm which one."

    return result
