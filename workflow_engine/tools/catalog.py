"""Authoritative Phase 0 inventory for tools that can be exposed to a model.

This catalog records the controls each tool requires.  It is intentionally
independent of procedure prompts so an unclassified tool fails closed before it
can be attached to an ADK agent.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Mapping

from workflow_engine.auth.models import Permission


class ToolOwner(str, Enum):
    CUSTOMER_SERVICE = "customer_service"
    FRAUD_OPERATIONS = "fraud_operations"
    SHARED_OPERATIONS = "shared_operations"
    KNOWLEDGE = "knowledge"


class RiskTier(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    REGULATED = "regulated"


class AuthorizationMode(str, Enum):
    READ_PERMISSION = "read_permission"
    ACTION_GATEWAY_REQUIRED = "action_gateway_required"
    PUBLIC_KNOWLEDGE = "public_knowledge"


class IdempotencyMode(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    NOT_IMPLEMENTED = "not_implemented"
    ACTION_GATEWAY = "action_gateway"


@dataclass(frozen=True)
class ToolControl:
    name: str
    owner: ToolOwner
    risk_tier: RiskTier
    consequential: bool
    required_permission: Permission | None
    authorization_mode: AuthorizationMode
    idempotency_mode: IdempotencyMode
    production_model_enabled: bool


def _read(
    name: str,
    owner: ToolOwner,
    permission: Permission | None,
    *,
    risk_tier: RiskTier = RiskTier.LOW,
) -> ToolControl:
    return ToolControl(
        name=name,
        owner=owner,
        risk_tier=risk_tier,
        consequential=False,
        required_permission=permission,
        authorization_mode=(
            AuthorizationMode.READ_PERMISSION
            if permission is not None
            else AuthorizationMode.PUBLIC_KNOWLEDGE
        ),
        idempotency_mode=IdempotencyMode.NOT_APPLICABLE,
        production_model_enabled=True,
    )


def _action(
    name: str,
    owner: ToolOwner,
    permission: Permission,
    risk_tier: RiskTier,
) -> ToolControl:
    return ToolControl(
        name=name,
        owner=owner,
        risk_tier=risk_tier,
        consequential=True,
        required_permission=permission,
        authorization_mode=AuthorizationMode.ACTION_GATEWAY_REQUIRED,
        idempotency_mode=IdempotencyMode.ACTION_GATEWAY,
        # Models never execute these operations directly. The v3 REST action
        # service creates a typed command and the independent gateway dispatches it.
        production_model_enabled=False,
    )


_ENTRIES = (
    _read("lookup_order", ToolOwner.CUSTOMER_SERVICE, Permission.ORDER_READ),
    _read("get_customer_profile", ToolOwner.CUSTOMER_SERVICE, Permission.CUSTOMER_READ),
    _read("search_orders", ToolOwner.CUSTOMER_SERVICE, Permission.ORDER_READ),
    _read("lookup_dispute", ToolOwner.CUSTOMER_SERVICE, Permission.CASE_READ),
    _read(
        "check_dispute_eligibility",
        ToolOwner.CUSTOMER_SERVICE,
        Permission.CASE_READ,
        risk_tier=RiskTier.MEDIUM,
    ),
    _read("get_knowledge_article", ToolOwner.KNOWLEDGE, None),
    _read("get_fraud_alert", ToolOwner.FRAUD_OPERATIONS, Permission.FRAUD_ALERT_READ),
    _read(
        "get_account_transactions",
        ToolOwner.FRAUD_OPERATIONS,
        Permission.TRANSACTION_READ,
        risk_tier=RiskTier.MEDIUM,
    ),
    _read(
        "check_device_fingerprint",
        ToolOwner.FRAUD_OPERATIONS,
        Permission.DEVICE_READ,
        risk_tier=RiskTier.MEDIUM,
    ),
    _action("issue_refund", ToolOwner.CUSTOMER_SERVICE, Permission.REFUND_WRITE, RiskTier.HIGH),
    _action("issue_store_credit", ToolOwner.CUSTOMER_SERVICE, Permission.REFUND_WRITE, RiskTier.HIGH),
    _action("update_case_status", ToolOwner.CUSTOMER_SERVICE, Permission.CASE_WRITE, RiskTier.MEDIUM),
    _action("file_eft_dispute", ToolOwner.CUSTOMER_SERVICE, Permission.CASE_WRITE, RiskTier.REGULATED),
    _action(
        "issue_provisional_credit",
        ToolOwner.CUSTOMER_SERVICE,
        Permission.REFUND_WRITE,
        RiskTier.REGULATED,
    ),
    _action(
        "escalate_to_supervisor",
        ToolOwner.SHARED_OPERATIONS,
        Permission.ESCALATION_CREATE,
        RiskTier.MEDIUM,
    ),
    _action("add_case_note", ToolOwner.SHARED_OPERATIONS, Permission.CASE_WRITE, RiskTier.MEDIUM),
    _action("flag_account", ToolOwner.FRAUD_OPERATIONS, Permission.ACCOUNT_FLAG, RiskTier.HIGH),
    _action("submit_sar", ToolOwner.FRAUD_OPERATIONS, Permission.SAR_SUBMIT, RiskTier.REGULATED),
    _action(
        "close_alert",
        ToolOwner.FRAUD_OPERATIONS,
        Permission.FRAUD_ALERT_WRITE,
        RiskTier.HIGH,
    ),
)

TOOL_CATALOG: dict[str, ToolControl] = {entry.name: entry for entry in _ENTRIES}

if len(TOOL_CATALOG) != len(_ENTRIES):
    raise RuntimeError("Duplicate tool name in TOOL_CATALOG")


def select_model_tools(
    tool_map: Mapping[str, Callable],
    *,
    production: bool,
) -> list[Callable]:
    """Return classified tools allowed for the current environment.

    Unknown tools raise instead of being silently exposed.  In production,
    consequential tools remain unavailable until the action gateway required by
    the catalog exists and their entries are deliberately changed.
    """
    selected: list[Callable] = []
    for name in sorted(tool_map):
        control = TOOL_CATALOG[name]
        if not production or control.production_model_enabled:
            selected.append(tool_map[name])
    return selected


def production_safety_instruction(tool_map: Mapping[str, Callable]) -> str:
    """Explain the safety freeze for actions omitted from a production agent."""
    frozen_actions = [
        name
        for name in sorted(tool_map)
        if not TOOL_CATALOG[name].production_model_enabled
    ]
    if not frozen_actions:
        return ""
    return (
        "PRODUCTION SAFETY FREEZE: The following actions are unavailable in this "
        f"channel: {', '.join(frozen_actions)}. Do not call, simulate, or imply "
        "execution of these actions. Never claim that a frozen action succeeded. "
        "You may gather information with available read tools, then clearly explain "
        "that an authorized human workflow is required to complete the action."
    )
