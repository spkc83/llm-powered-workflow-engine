"""Agent guardrails for output filtering and safety.

Prevents agents from leaking internal data, making unauthorized promises,
hallucinating policy, or producing harmful content.
"""

import re
from typing import Optional

from ..logging_config import get_logger

logger = get_logger("agents.guardrails")


class GuardrailViolation:
    """A detected guardrail violation."""

    def __init__(self, rule: str, description: str, severity: str = "warning"):
        self.rule = rule
        self.description = description
        self.severity = severity  # "warning", "block", "redact"

    def __repr__(self) -> str:
        return f"GuardrailViolation(rule={self.rule!r}, severity={self.severity!r})"


# --- Guardrail rules ---

# Patterns that should never appear in agent responses to customers
_INTERNAL_DATA_PATTERNS = [
    (r"(?i)\bstep[_ ]?id\b.*?:", "internal_step_id", "Agent is exposing internal step IDs"),
    (r"(?i)\bprocedure[_ ]?id\b.*?:", "internal_procedure_id", "Agent is exposing internal procedure IDs"),
    (r"(?i)\b(sql|query|database|db_path|sqlite)\b", "internal_db_reference", "Agent is referencing internal database details"),
    (r"(?i)\btool_context\b", "internal_tool_context", "Agent is referencing internal tool context"),
    (r"(?i)\bsession[_ ]?state\b", "internal_session_state", "Agent is referencing session state internals"),
    (r"(?i)\b(api_key|secret_key|password|credential)\b", "sensitive_credential", "Agent is mentioning credentials"),
]

# Patterns for unauthorized promises
_UNAUTHORIZED_PROMISE_PATTERNS = [
    (r"(?i)\bi\s+(?:guarantee|promise|assure)\s+(?:you|that)", "unauthorized_promise", "Agent is making unauthorized guarantees"),
    (r"(?i)\b100%\s+(?:guaranteed|certain|sure)\b", "false_certainty", "Agent is expressing false certainty"),
]

# Financial compliance patterns
_COMPLIANCE_PATTERNS = [
    (r"(?i)\b(?:legal|financial)\s+advice\b", "unauthorized_advice", "Agent may be providing unauthorized financial/legal advice"),
    (r"(?i)\b(?:you\s+should|i\s+recommend)\s+(?:invest|buy\s+stock|sell\s+stock)", "investment_advice", "Agent is providing investment advice"),
]


def check_response(text: str, domain: str = "customer_service") -> list[GuardrailViolation]:
    """Check an agent response for guardrail violations.

    Args:
        text: The agent's response text.
        domain: The agent domain context (customer_service, fraud_ops).

    Returns:
        List of detected violations (empty if clean).
    """
    violations: list[GuardrailViolation] = []

    # Check internal data leakage
    for pattern, rule, desc in _INTERNAL_DATA_PATTERNS:
        if re.search(pattern, text):
            violations.append(GuardrailViolation(rule, desc, severity="redact"))

    # Check unauthorized promises
    for pattern, rule, desc in _UNAUTHORIZED_PROMISE_PATTERNS:
        if re.search(pattern, text):
            violations.append(GuardrailViolation(rule, desc, severity="warning"))

    # Check compliance
    for pattern, rule, desc in _COMPLIANCE_PATTERNS:
        if re.search(pattern, text):
            violations.append(GuardrailViolation(rule, desc, severity="warning"))

    if violations:
        logger.warning(
            "Guardrail violations detected (%d): %s",
            len(violations),
            [v.rule for v in violations],
        )

    return violations


def filter_response(text: str, domain: str = "customer_service") -> tuple[str, list[GuardrailViolation]]:
    """Check and filter an agent response, redacting sensitive content.

    Args:
        text: The agent's response text.
        domain: The agent domain context.

    Returns:
        Tuple of (filtered_text, violations).
    """
    violations = check_response(text, domain)
    filtered = text

    for violation in violations:
        if violation.severity == "redact":
            # Redact the specific pattern match
            for pattern, rule, _ in _INTERNAL_DATA_PATTERNS:
                if rule == violation.rule:
                    filtered = re.sub(pattern, "[REDACTED]", filtered)

    return filtered, violations


def validate_tool_args(tool_name: str, args: dict) -> list[GuardrailViolation]:
    """Validate tool arguments for safety before execution.

    Args:
        tool_name: The tool being called.
        args: The arguments the LLM is passing to the tool.

    Returns:
        List of violations (empty if valid).
    """
    violations: list[GuardrailViolation] = []

    # Validate amount fields are positive
    for field in ("amount", "total"):
        if field in args and args[field] is not None:
            try:
                val = float(args[field])
                if val < 0:
                    violations.append(GuardrailViolation(
                        "negative_amount",
                        f"Tool '{tool_name}' received negative {field}: {val}",
                        severity="block",
                    ))
            except (ValueError, TypeError):
                pass

    # Validate ID format patterns
    id_patterns = {
        "order_id": r"^ORD-\d+$",
        "customer_id": r"^CUST-\d+$",
        "alert_id": r"^FA-\d+$",
        "account_id": r"^ACCT-\d+$",
    }
    for field, pattern in id_patterns.items():
        if field in args and args[field]:
            if not re.match(pattern, args[field]):
                violations.append(GuardrailViolation(
                    f"invalid_{field}_format",
                    f"Tool '{tool_name}' received malformed {field}: {args[field]}",
                    severity="warning",
                ))

    # Validate string length limits (prevent prompt injection via tool args)
    max_lengths = {"reason": 1000, "notes": 2000, "note": 2000, "findings": 5000, "query": 500}
    for field, max_len in max_lengths.items():
        if field in args and isinstance(args[field], str) and len(args[field]) > max_len:
            violations.append(GuardrailViolation(
                "input_too_long",
                f"Tool '{tool_name}' field '{field}' exceeds max length ({len(args[field])} > {max_len})",
                severity="block",
            ))

    if violations:
        logger.warning(
            "Tool arg violations for '%s': %s",
            tool_name,
            [v.rule for v in violations],
        )

    return violations
