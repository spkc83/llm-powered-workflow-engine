"""Fraud operations tools.

Uses the repository pattern for data access and the audit logger
for compliance-critical actions (account flags, SARs, alert closures).
"""

from datetime import datetime, timedelta

from google.adk.tools import ToolContext

from workflow_engine.audit import AuditAction, get_audit_logger
from workflow_engine.database.repository import (
    AccountRepository,
    CaseRepository,
    DeviceRepository,
    FraudAlertRepository,
    TransactionRepository,
)
from workflow_engine.logging_config import get_logger

logger = get_logger("tools.fraud")


async def get_fraud_alert(alert_id: str, tool_context: ToolContext) -> dict:
    """Retrieve fraud alert details by alert ID.

    Args:
        alert_id: The fraud alert ID (e.g., "FA-001").
    """
    logger.info("Retrieving fraud alert: %s", alert_id)

    alert = await FraudAlertRepository.get_by_id(alert_id)
    if alert is None:
        return {"error": f"Alert {alert_id} not found", "found": False}

    result = {**alert, "found": True}
    tool_context.state["alert_data"] = alert
    tool_context.state["account_id"] = alert["account_id"]

    # Audit
    audit = get_audit_logger()
    await audit.log(
        action=AuditAction.FRAUD_ALERT_VIEWED,
        actor=tool_context.state.get("customer_id", "analyst"),
        resource_type="fraud_alert",
        resource_id=alert_id,
        session_id=str(getattr(tool_context, "session_id", None)),
        metadata={"severity": alert["severity"], "risk_score": alert["risk_score"]},
    )

    return result


async def get_account_transactions(account_id: str, days: int, tool_context: ToolContext) -> dict:
    """Get recent transactions for an account.

    Args:
        account_id: The account ID to look up transactions for.
        days: Number of days of transaction history to retrieve.
    """
    logger.info("Retrieving transactions for account=%s days=%d", account_id, days)

    transactions = await TransactionRepository.get_by_account(account_id)

    total_amount = sum(t["amount"] for t in transactions)
    flagged = [t for t in transactions if t["is_flagged"]]
    flagged_amount = sum(t["amount"] for t in flagged)

    data = {
        "account_id": account_id,
        "transactions": transactions,
        "summary": {
            "total_transactions": len(transactions),
            "flagged_count": len(flagged),
            "total_amount": total_amount,
            "flagged_amount": flagged_amount,
        },
    }

    tool_context.state["transaction_data"] = data

    # Audit
    audit = get_audit_logger()
    await audit.log(
        action=AuditAction.TRANSACTIONS_VIEWED,
        actor=tool_context.state.get("customer_id", "analyst"),
        resource_type="transactions",
        resource_id=account_id,
        session_id=str(getattr(tool_context, "session_id", None)),
        metadata={"days": days, "count": len(transactions), "flagged": len(flagged)},
    )

    return data


async def check_device_fingerprint(account_id: str, tool_context: ToolContext) -> dict:
    """Check device fingerprint and login history for an account.

    Args:
        account_id: The account ID to check device info for.
    """
    logger.info("Checking device fingerprint for account=%s", account_id)

    devices = await DeviceRepository.get_devices(account_id)
    logins = await DeviceRepository.get_login_history(account_id)
    indicators = await DeviceRepository.get_risk_indicators(account_id)

    known_devices = [
        {**d, "trusted": bool(d["trusted"])} for d in devices
    ]
    recent_logins = [
        {**login, "is_new": bool(login["is_new"])} for login in logins
    ]

    data = {
        "account_id": account_id,
        "known_devices": known_devices,
        "recent_logins": recent_logins,
        "risk_indicators": indicators,
    }

    if not devices and not logins:
        data["risk_indicators"] = ["unknown_account"]

    tool_context.state["device_data"] = data

    # Audit
    audit = get_audit_logger()
    await audit.log(
        action=AuditAction.DEVICE_CHECK,
        actor=tool_context.state.get("customer_id", "analyst"),
        resource_type="device_fingerprint",
        resource_id=account_id,
        session_id=str(getattr(tool_context, "session_id", None)),
        metadata={
            "devices_count": len(devices),
            "logins_count": len(logins),
            "risk_indicators": indicators,
        },
    )

    return data


async def flag_account(account_id: str, reason: str, action: str, tool_context: ToolContext) -> dict:
    """Flag an account for fraud and take protective action.

    Args:
        account_id: The account ID to flag.
        reason: Reason for flagging the account.
        action: Action to take (e.g., "freeze", "restrict", "monitor").
    """
    now = datetime.now()
    case_number = f"FRAUD-{now.strftime('%Y%m%d%H%M%S')}"

    logger.info("Flagging account %s: action=%s reason=%s", account_id, action, reason)

    # Get before state for audit
    before_account = await AccountRepository.get_by_id(account_id)
    before_status = before_account["status"] if before_account else "unknown"

    await AccountRepository.update_status(account_id, action)

    await CaseRepository.upsert(
        case_id=case_number,
        status="account_flagged",
        notes=reason,
        customer_id=account_id,
    )

    result = {
        "account_id": account_id,
        "action_taken": action,
        "reason": reason,
        "flagged_at": now.isoformat(),
        "case_number": case_number,
        "status": "account_flagged",
        "next_steps": "Account has been flagged. Customer will be notified via secure channel.",
    }

    tool_context.state["account_flagged"] = True
    tool_context.state["fraud_case_number"] = result["case_number"]

    # Audit — compliance-critical
    audit = get_audit_logger()
    await audit.log(
        action=AuditAction.ACCOUNT_FLAGGED,
        actor=tool_context.state.get("customer_id", "analyst"),
        resource_type="account",
        resource_id=account_id,
        session_id=str(getattr(tool_context, "session_id", None)),
        before_state={"status": before_status},
        after_state={"status": action},
        metadata={
            "reason": reason,
            "action_taken": action,
            "case_number": case_number,
        },
    )

    return result


async def submit_sar(account_id: str, alert_id: str, findings: str, tool_context: ToolContext) -> dict:
    """Submit a Suspicious Activity Report (SAR).

    Args:
        account_id: The account ID associated with the suspicious activity.
        alert_id: The fraud alert ID that triggered the investigation.
        findings: Summary of investigation findings.
    """
    now = datetime.now()
    sar_id = f"SAR-{now.strftime('%Y%m%d%H%M%S')}"

    logger.info("Submitting SAR %s for account=%s alert=%s", sar_id, account_id, alert_id)

    result = {
        "sar_id": sar_id,
        "account_id": account_id,
        "alert_id": alert_id,
        "findings": findings,
        "status": "submitted",
        "submitted_at": now.isoformat(),
        "review_deadline": (now + timedelta(days=30)).strftime("%Y-%m-%d"),
    }

    tool_context.state["sar_submitted"] = True
    tool_context.state["sar_id"] = result["sar_id"]

    # Audit — compliance-critical (regulatory requirement)
    audit = get_audit_logger()
    await audit.log(
        action=AuditAction.SAR_SUBMITTED,
        actor=tool_context.state.get("customer_id", "analyst"),
        resource_type="sar",
        resource_id=sar_id,
        session_id=str(getattr(tool_context, "session_id", None)),
        metadata={
            "account_id": account_id,
            "alert_id": alert_id,
            "review_deadline": result["review_deadline"],
            "findings_length": len(findings),
        },
    )

    return result


async def close_alert(alert_id: str, resolution: str, tool_context: ToolContext) -> dict:
    """Close a fraud alert with a resolution.

    Args:
        alert_id: The alert ID to close.
        resolution: Resolution description (e.g., "confirmed_fraud", "false_positive", "escalated").
    """
    now = datetime.now().isoformat()

    logger.info("Closing alert %s with resolution=%s", alert_id, resolution)

    await FraudAlertRepository.close(alert_id)

    result = {
        "alert_id": alert_id,
        "resolution": resolution,
        "closed_at": now,
        "closed_by": "fraud_analyst",
        "status": "closed",
    }

    tool_context.state["alert_status"] = "closed"
    tool_context.state["alert_resolution"] = resolution

    # Audit
    audit = get_audit_logger()
    await audit.log(
        action=AuditAction.ALERT_CLOSED,
        actor=tool_context.state.get("customer_id", "analyst"),
        resource_type="fraud_alert",
        resource_id=alert_id,
        session_id=str(getattr(tool_context, "session_id", None)),
        after_state={"status": "closed", "resolution": resolution},
    )

    return result
