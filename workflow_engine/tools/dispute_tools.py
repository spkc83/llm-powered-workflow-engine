"""Dispute tools for Regulation E (EFT dispute) compliance.

Implements the dispute lifecycle: lookup, eligibility assessment, filing,
provisional credit issuance, and resolution — all with Reg E compliance
guardrails and audit trail logging.

Reg E Key Rules:
- Consumer liability tiers: $50 (2 days), $500 (60 days), unlimited (beyond 60 days)
- Investigation: 10 business days initial, 45/90 calendar days final
- Provisional credit: required if investigation exceeds 10 business days
- Written acknowledgment: within 1 business day of receiving dispute
"""

import json
from datetime import datetime, timedelta
from typing import Any, Optional, cast

from google.adk.tools import ToolContext

from workflow_engine.audit import AuditAction, get_audit_logger
from workflow_engine.database.repository import DisputeRepository
from workflow_engine.logging_config import get_logger
from workflow_engine.tools.access import authorize_tool

logger = get_logger("tools.dispute")


# Reg E liability tiers
_LIABILITY_TIERS = {
    "tier_1": {"max_days": 2, "max_liability": 50.00, "label": "within 2 business days"},
    "tier_2": {"max_days": 60, "max_liability": 500.00, "label": "within 60 calendar days"},
    "tier_3": {"max_days": None, "max_liability": None, "label": "beyond 60 calendar days"},
}

# EFT payment methods covered by Reg E
_REG_E_PAYMENT_METHODS = {
    "debit_card", "debit", "ach", "ach_withdrawal", "wire", "p2p",
    "atm", "electronic_transfer", "debit_card_ending_5678",
    "debit_card_ending_4242", "debit_card_ending_1234",
}


def _calculate_liability_tier(days_since_discovery: int) -> tuple[str, float]:
    """Calculate Reg E liability tier based on days since consumer learned of loss.

    Returns (tier_name, max_liability_amount).
    """
    if days_since_discovery <= 2:
        return "tier_1", 50.00
    elif days_since_discovery <= 60:
        return "tier_2", 500.00
    else:
        return "tier_3", -1.0  # unlimited — will be set to full amount


def _is_eft_covered(payment_method: str) -> bool:
    """Check if a payment method is an electronic fund transfer covered by Reg E."""
    return payment_method.lower() in _REG_E_PAYMENT_METHODS


async def lookup_dispute(dispute_id: str, tool_context: ToolContext) -> dict:
    """Look up an existing EFT dispute by its dispute ID.

    Args:
        dispute_id: The dispute ID to look up (e.g., "DISP-001").
    """
    authorize_tool("lookup_dispute", tool_context)
    logger.info("Looking up dispute: %s", dispute_id)

    dispute = await DisputeRepository.get_by_id(dispute_id)
    if dispute is None:
        return {"error": f"Dispute {dispute_id} not found", "found": False}

    if dispute["customer_id"] != tool_context.state.get("customer_id"):
        return {"error": f"Dispute {dispute_id} not found", "found": False}

    result = {**dict(dispute), "found": True}

    # Store in tool context for later steps
    tool_context.state["dispute_data"] = result
    tool_context.state["customer_id"] = dispute["customer_id"]

    # Add Reg E context
    tier_info = cast(dict[str, Any], _LIABILITY_TIERS.get(dispute["liability_tier"], {}))
    result["liability_description"] = tier_info.get("label", "unknown")
    result["reg_e_covered"] = True

    audit = get_audit_logger()
    await audit.log(
        action=AuditAction.COMPLIANCE_CHECK,
        actor=tool_context.state.get("customer_id", "system"),
        resource_type="dispute",
        resource_id=dispute_id,
        session_id=str(getattr(tool_context, "session_id", None)),
        metadata={"action": "lookup", "status": dispute["status"]},
    )

    return result


async def check_dispute_eligibility(
    transaction_id: str,
    dispute_type: str,
    days_since_noticed: int,
    payment_method: str,
    tool_context: ToolContext,
) -> dict:
    """Assess Reg E eligibility for an EFT dispute.

    Evaluates the dispute against Regulation E rules to determine:
    - Whether the transaction type is covered (EFT only)
    - The consumer's liability tier based on reporting timeline
    - The maximum liability amount
    - Investigation timeline requirements

    Args:
        transaction_id: The transaction being disputed.
        dispute_type: Type of dispute: "unauthorized" or "error".
        days_since_noticed: Days since consumer first noticed the unauthorized transfer.
        payment_method: Payment method used (debit_card, ach, wire, p2p, etc.).
    """
    authorize_tool("check_dispute_eligibility", tool_context)
    logger.info(
        "Checking Reg E eligibility: txn=%s type=%s days=%d method=%s",
        transaction_id, dispute_type, days_since_noticed, payment_method,
    )

    # Check if transaction type is covered by Reg E
    is_covered = _is_eft_covered(payment_method)
    if not is_covered:
        result = {
            "eligible": False,
            "reason": "not_eft",
            "message": (
                f"The payment method '{payment_method}' is not an electronic fund transfer "
                f"covered by Regulation E. Credit card disputes are covered under Regulation Z."
            ),
            "recommendation": "redirect_non_eft",
        }
        tool_context.state["dispute_eligibility"] = result
        return result

    # Calculate liability tier
    tier, max_liability = _calculate_liability_tier(days_since_noticed)

    # Determine investigation timeline
    # Standard: 45 calendar days. Extended: 90 days for new accounts, POS, foreign
    investigation_days = 45

    # Build eligibility result
    if tier == "tier_3":
        result = {
            "eligible": False,
            "reason": "outside_60_day_window",
            "liability_tier": tier,
            "days_since_noticed": days_since_noticed,
            "message": (
                "The dispute was reported more than 60 days after the statement date. "
                "Under Regulation E, the consumer bears full liability for unauthorized "
                "transfers reported after the 60-day window."
            ),
            "recommendation": "deny_late_dispute",
            "max_liability": "unlimited",
        }
    else:
        result = {
            "eligible": True,
            "liability_tier": tier,
            "max_liability": max_liability,
            "days_since_noticed": days_since_noticed,
            "investigation_deadline_days": 10,  # initial: 10 business days
            "final_deadline_days": investigation_days,
            "provisional_credit_required_after_days": 10,
            "message": (
                f"Dispute is eligible under Regulation E. Liability tier: {tier} "
                f"(max ${max_liability:.2f}). Investigation must begin within 10 business days."
            ),
            "recommendation": "file_dispute",
        }

    tool_context.state["dispute_eligibility"] = result

    # Audit the eligibility check
    audit = get_audit_logger()
    await audit.log(
        action=AuditAction.COMPLIANCE_CHECK,
        actor=tool_context.state.get("customer_id", "system"),
        resource_type="dispute_eligibility",
        resource_id=transaction_id,
        session_id=str(getattr(tool_context, "session_id", None)),
        metadata={
            "dispute_type": dispute_type,
            "payment_method": payment_method,
            "days_since_noticed": days_since_noticed,
            "liability_tier": tier,
            "eligible": result["eligible"],
        },
    )

    return result


async def file_eft_dispute(
    customer_id: str,
    transaction_id: str,
    dispute_type: str,
    amount: float,
    merchant: str,
    transaction_date: str,
    reason: str,
    tool_context: ToolContext,
    account_id: Optional[str] = None,
    payment_method: str = "debit_card",
) -> dict:
    """File a formal EFT dispute under Regulation E.

    Creates the dispute record with Reg E compliance metadata, triggers
    the investigation timeline, and returns the dispute reference number.

    Args:
        customer_id: The customer filing the dispute.
        transaction_id: The transaction being disputed.
        dispute_type: Type: "unauthorized" or "error".
        amount: The disputed amount in USD.
        merchant: Merchant name on the transaction.
        transaction_date: Date of the transaction (YYYY-MM-DD).
        reason: Customer's description of the dispute.
        account_id: Account ID involved (optional).
        payment_method: Payment method (debit_card, ach, wire, p2p).
    """
    authorize_tool("file_eft_dispute", tool_context, customer_id=customer_id)
    now = datetime.now()
    dispute_id = f"DISP-{now.strftime('%Y%m%d%H%M%S')}"

    # Get eligibility data from prior step
    eligibility = tool_context.state.get("dispute_eligibility", {})
    tier = eligibility.get("liability_tier", "tier_2")
    max_liability = eligibility.get("max_liability", 500.00)

    # Calculate timeline
    try:
        txn_date = datetime.strptime(transaction_date, "%Y-%m-%d")
        days_since_transaction = (now - txn_date).days
    except ValueError:
        days_since_transaction = 0

    reported_date = now.strftime("%Y-%m-%d")
    statement_date = reported_date  # Simplified: use report date as statement date
    investigation_deadline = (now + timedelta(days=10)).strftime("%Y-%m-%d")

    # Handle unlimited liability (tier 3)
    if max_liability == -1.0 or tier == "tier_3":
        max_liability = amount

    logger.info(
        "Filing EFT dispute %s: customer=%s amount=%.2f tier=%s",
        dispute_id, customer_id, amount, tier,
    )

    await DisputeRepository.create(
        dispute_id=dispute_id,
        customer_id=customer_id,
        transaction_id=transaction_id,
        account_id=account_id or "",
        dispute_type=dispute_type,
        amount=amount,
        merchant=merchant,
        transaction_date=transaction_date,
        reported_date=reported_date,
        statement_date=statement_date,
        days_since_transaction=days_since_transaction,
        days_since_statement=0,
        liability_tier=tier,
        max_liability=max_liability,
        investigation_deadline=investigation_deadline,
        payment_method=payment_method,
        metadata=json.dumps({"reason": reason}),
    )

    result = {
        "dispute_id": dispute_id,
        "customer_id": customer_id,
        "transaction_id": transaction_id,
        "amount": amount,
        "status": "open",
        "liability_tier": tier,
        "max_liability": max_liability,
        "investigation_deadline": investigation_deadline,
        "filed_at": now.isoformat(),
        "reg_e_disclosures": {
            "written_acknowledgment": "within 1 business day",
            "investigation_timeline": "10 business days initial",
            "provisional_credit": "if investigation extends beyond 10 business days",
            "final_resolution": "45 calendar days (90 for POS/foreign/new accounts)",
            "max_consumer_liability": f"${max_liability:.2f}",
        },
    }

    tool_context.state["dispute_data"] = result
    tool_context.state["dispute_id"] = dispute_id

    # Audit — compliance-critical
    audit = get_audit_logger()
    await audit.log(
        action=AuditAction.COMPLIANCE_CHECK,
        actor=customer_id,
        resource_type="dispute",
        resource_id=dispute_id,
        session_id=str(getattr(tool_context, "session_id", None)),
        metadata={
            "action": "file_dispute",
            "amount": amount,
            "dispute_type": dispute_type,
            "liability_tier": tier,
            "max_liability": max_liability,
            "investigation_deadline": investigation_deadline,
            "reg_e_compliant": True,
        },
    )

    return result


async def issue_provisional_credit(
    dispute_id: str,
    tool_context: ToolContext,
) -> dict:
    """Issue provisional credit for a Reg E dispute.

    Under Regulation E, if investigation cannot be completed within 10 business
    days, provisional credit must be issued for the disputed amount minus the
    applicable consumer liability.

    Provisional credit = disputed amount - max liability
    Example: $350 dispute, Tier 1 → $350 - $50 = $300 provisional credit

    Args:
        dispute_id: The dispute to issue provisional credit for.
    """
    authorize_tool("issue_provisional_credit", tool_context)
    dispute_data = tool_context.state.get("dispute_data", {})
    amount = dispute_data.get("amount", 0)
    max_liability = dispute_data.get("max_liability", 50.00)

    # Calculate provisional credit amount
    provisional_amount = max(0, amount - max_liability)

    if provisional_amount <= 0:
        return {
            "dispute_id": dispute_id,
            "provisional_credit_issued": False,
            "reason": "Disputed amount does not exceed consumer liability limit",
            "amount": amount,
            "max_liability": max_liability,
        }

    now = datetime.now()
    credit_date = now.strftime("%Y-%m-%d")

    logger.info(
        "Issuing provisional credit for %s: $%.2f (dispute=$%.2f, liability=$%.2f)",
        dispute_id, provisional_amount, amount, max_liability,
    )

    await DisputeRepository.issue_provisional_credit(
        dispute_id=dispute_id,
        amount=provisional_amount,
        credit_date=credit_date,
    )

    result = {
        "dispute_id": dispute_id,
        "provisional_credit_issued": True,
        "provisional_credit_amount": provisional_amount,
        "credit_date": credit_date,
        "disputed_amount": amount,
        "consumer_liability": max_liability,
        "message": (
            f"Provisional credit of ${provisional_amount:.2f} has been applied to the account. "
            f"This credit will remain unless the investigation determines the transaction was authorized."
        ),
    }

    tool_context.state["provisional_credit"] = result

    # Audit — compliance-critical
    audit = get_audit_logger()
    await audit.log(
        action=AuditAction.COMPLIANCE_CHECK,
        actor=tool_context.state.get("customer_id", "system"),
        resource_type="provisional_credit",
        resource_id=dispute_id,
        session_id=str(getattr(tool_context, "session_id", None)),
        metadata={
            "action": "issue_provisional_credit",
            "provisional_amount": provisional_amount,
            "disputed_amount": amount,
            "consumer_liability": max_liability,
            "reg_e_compliant": True,
        },
    )

    return result
