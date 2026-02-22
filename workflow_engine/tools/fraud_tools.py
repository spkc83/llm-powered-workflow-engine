"""Fraud operations tools, backed by SQLite."""

from datetime import datetime, timedelta

from google.adk.tools import ToolContext

from workflow_engine.database.db import execute, query_all, query_one


async def get_fraud_alert(alert_id: str, tool_context: ToolContext) -> dict:
    """Retrieve fraud alert details by alert ID.

    Args:
        alert_id: The fraud alert ID (e.g., "FA-001").
    """
    alert = await query_one(
        "SELECT * FROM fraud_alerts WHERE alert_id = ?",
        (alert_id,),
    )
    if alert is None:
        return {"error": f"Alert {alert_id} not found", "found": False}

    result = {**alert, "found": True}
    tool_context.state["alert_data"] = alert
    tool_context.state["account_id"] = alert["account_id"]

    return result


async def get_account_transactions(account_id: str, days: int, tool_context: ToolContext) -> dict:
    """Get recent transactions for an account.

    Args:
        account_id: The account ID to look up transactions for.
        days: Number of days of transaction history to retrieve.
    """
    transactions = await query_all(
        "SELECT * FROM transactions WHERE account_id = ? ORDER BY date DESC",
        (account_id,),
    )

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
    return data


async def check_device_fingerprint(account_id: str, tool_context: ToolContext) -> dict:
    """Check device fingerprint and login history for an account.

    Args:
        account_id: The account ID to check device info for.
    """
    devices = await query_all(
        "SELECT * FROM devices WHERE account_id = ?",
        (account_id,),
    )
    logins = await query_all(
        "SELECT * FROM login_history WHERE account_id = ? ORDER BY timestamp DESC",
        (account_id,),
    )
    indicators = await query_all(
        "SELECT indicator FROM risk_indicators WHERE account_id = ?",
        (account_id,),
    )

    known_devices = [
        {**d, "trusted": bool(d["trusted"])} for d in devices
    ]
    recent_logins = [
        {**l, "is_new": bool(l["is_new"])} for l in logins
    ]

    data = {
        "account_id": account_id,
        "known_devices": known_devices,
        "recent_logins": recent_logins,
        "risk_indicators": [r["indicator"] for r in indicators],
    }

    if not devices and not logins:
        data["risk_indicators"] = ["unknown_account"]

    tool_context.state["device_data"] = data
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

    await execute(
        "UPDATE accounts SET status = ? WHERE account_id = ?",
        (action, account_id),
    )

    await execute(
        "INSERT OR IGNORE INTO cases (case_id, customer_id, status, created_at, notes) VALUES (?, ?, ?, ?, ?)",
        (case_number, account_id, "account_flagged", now.isoformat(), reason),
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

    return result


async def submit_sar(account_id: str, alert_id: str, findings: str, tool_context: ToolContext) -> dict:
    """Submit a Suspicious Activity Report (SAR).

    Args:
        account_id: The account ID associated with the suspicious activity.
        alert_id: The fraud alert ID that triggered the investigation.
        findings: Summary of investigation findings.
    """
    now = datetime.now()
    result = {
        "sar_id": f"SAR-{now.strftime('%Y%m%d%H%M%S')}",
        "account_id": account_id,
        "alert_id": alert_id,
        "findings": findings,
        "status": "submitted",
        "submitted_at": now.isoformat(),
        "review_deadline": (now + timedelta(days=30)).strftime("%Y-%m-%d"),
    }

    tool_context.state["sar_submitted"] = True
    tool_context.state["sar_id"] = result["sar_id"]

    return result


async def close_alert(alert_id: str, resolution: str, tool_context: ToolContext) -> dict:
    """Close a fraud alert with a resolution.

    Args:
        alert_id: The alert ID to close.
        resolution: Resolution description (e.g., "confirmed_fraud", "false_positive", "escalated").
    """
    now = datetime.now().isoformat()

    await execute(
        "UPDATE fraud_alerts SET status = 'closed' WHERE alert_id = ?",
        (alert_id,),
    )

    result = {
        "alert_id": alert_id,
        "resolution": resolution,
        "closed_at": now,
        "closed_by": "fraud_analyst",
        "status": "closed",
    }

    tool_context.state["alert_status"] = "closed"
    tool_context.state["alert_resolution"] = resolution

    return result
