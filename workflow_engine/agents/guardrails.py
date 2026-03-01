"""Agent guardrails for output filtering and safety.

Prevents agents from leaking internal data, making unauthorized promises,
hallucinating policy, or producing harmful content.

Enhanced with automated reasoning (Z3/SymPy) for formal verification of
LLM claims against procedure rules, plus a behavior steering loop that
rewrites invalid responses.

Pipeline layers:
  1. Pattern Rails  — regex-based, fast first pass (existing)
  2. Reasoning Rails — Z3 verification against formal procedure rules (NEW)
  3. Compliance Rails — domain-specific financial/procedural checks (NEW)
  4. Behavior Steering — rewrite loop for invalid responses (NEW)
"""

import re
from typing import Any, Callable, Coroutine, Optional

from ..logging_config import get_logger
from ..settings import get_settings

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


# ---------------------------------------------------------------------------
# Automated reasoning integration
# ---------------------------------------------------------------------------

# Lazy imports to avoid startup cost when reasoning is disabled
_reasoning_engine = None
_compliance_checker = None


def _get_reasoning_engine():
    """Lazy-load the reasoning engine."""
    global _reasoning_engine
    if _reasoning_engine is None:
        from .reasoning import ReasoningEngine
        _reasoning_engine = ReasoningEngine()
    return _reasoning_engine


def _get_compliance_checker():
    """Lazy-load the compliance checker."""
    global _compliance_checker
    if _compliance_checker is None:
        from .compliance import ComplianceChecker
        _compliance_checker = ComplianceChecker()
    return _compliance_checker


# Type alias for the LLM regeneration callback
GenerateFn = Callable[[str], Coroutine[Any, Any, str]]

# Safe fallback when steering exhausts all iterations
_SAFE_FALLBACK = (
    "I apologize, but I'm unable to provide accurate information about your "
    "request at this time. Let me connect you with a specialist who can help. "
    "Please hold while I transfer your case."
)

# Rewrite prompt template for behavior steering
_REWRITE_PROMPT_TEMPLATE = """The previous response was found to contain errors by our automated verification system.

Verification verdict: {verdict}
Explanation: {explanation}

Specific issues:
{rewrite_hint}

Original customer question context: The customer is in a {procedure_id} workflow at step '{current_step}'.
Session facts: {session_facts}

Please generate a corrected response that:
1. Addresses the customer's needs accurately
2. Does NOT violate the rules cited above
3. Uses the actual order/session data provided
"""


async def steer_response(
    text: str,
    session_state: dict,
    procedure_id: Optional[str] = None,
    current_step: Optional[str] = None,
    procedure_def: Optional[dict] = None,
    generate_fn: Optional[GenerateFn] = None,
    max_iterations: Optional[int] = None,
) -> tuple[str, list[GuardrailViolation], Any]:
    """Verify and steer LLM response using automated reasoning.

    Runs a layered guardrail pipeline:
      1. Pattern rails (existing regex — fast first pass)
      2. Reasoning rails (Z3 verification against procedure rules)
      3. Compliance rails (financial + procedural compliance)
      4. If INVALID: construct rewrite prompt with failure feedback,
         re-invoke LLM via generate_fn, re-verify (up to max_iterations)
      5. If still invalid after iterations: return safe fallback

    Args:
        text: The LLM response text.
        session_state: Session state dict with actual values.
        procedure_id: Active procedure ID, if any.
        current_step: Current procedure step ID, if any.
        procedure_def: Full procedure definition dict for rule extraction.
        generate_fn: Async callback to re-invoke LLM with a rewrite prompt.
                     Signature: async def generate(prompt: str) -> str
        max_iterations: Max rewrite attempts (default from settings).

    Returns:
        Tuple of (final_text, pattern_violations, verification_result_or_None).
    """
    from .reasoning import VerificationResult, build_policy_from_procedure
    from ..audit import AuditAction, get_audit_logger

    settings = get_settings()
    if max_iterations is None:
        max_iterations = settings.reasoning_max_iterations

    audit = get_audit_logger()

    # --- Layer 1: Pattern Rails (existing, always runs) ---
    text, pattern_violations = filter_response(text)

    # If reasoning is disabled, return after pattern rails only
    if not settings.reasoning_enabled:
        return text, pattern_violations, None

    # --- Layer 2 & 3: Reasoning + Compliance Rails ---
    verification: Optional[VerificationResult] = None

    # Build policy from procedure definition if available
    policy = None
    if procedure_def:
        policy = build_policy_from_procedure(procedure_def)

    for iteration in range(max_iterations + 1):
        verification = _run_verification(
            text, session_state, procedure_id, current_step, policy,
        )

        if verification is None or verification.is_valid or verification.verdict == "NOT_APPLICABLE":
            # Log successful verification
            if verification and verification.is_valid:
                await audit.log(
                    action=AuditAction.REASONING_VERIFIED,
                    actor="guardrails",
                    resource_type="response",
                    resource_id=procedure_id or "unknown",
                    session_id=session_state.get("_session_id"),
                    procedure_id=procedure_id,
                    step_id=current_step,
                    metadata={
                        "verdict": verification.verdict,
                        "cited_rules": verification.cited_rules,
                        "iteration": iteration,
                    },
                )
            break

        # Log the violation
        await audit.log(
            action=AuditAction.REASONING_VIOLATION,
            actor="guardrails",
            resource_type="response",
            resource_id=procedure_id or "unknown",
            session_id=session_state.get("_session_id"),
            procedure_id=procedure_id,
            step_id=current_step,
            metadata={
                "verdict": verification.verdict,
                "explanation": verification.explanation,
                "findings_count": len(verification.findings),
                "cited_rules": verification.cited_rules,
                "iteration": iteration,
            },
        )

        # --- Layer 4: Behavior Steering ---
        if iteration < max_iterations and generate_fn and verification.rewrite_hint:
            logger.warning(
                "Reasoning verification INVALID (iteration %d/%d), attempting rewrite",
                iteration + 1, max_iterations,
            )

            # Build rewrite prompt
            session_facts = _extract_session_facts(session_state)
            rewrite_prompt = _REWRITE_PROMPT_TEMPLATE.format(
                verdict=verification.verdict,
                explanation=verification.explanation,
                rewrite_hint=verification.rewrite_hint,
                procedure_id=procedure_id or "unknown",
                current_step=current_step or "unknown",
                session_facts=session_facts,
            )

            try:
                text = await generate_fn(rewrite_prompt)
                # Re-apply pattern rails to rewritten text
                text, new_violations = filter_response(text)
                pattern_violations.extend(new_violations)

                # Log the rewrite attempt
                await audit.log(
                    action=AuditAction.REASONING_REWRITE,
                    actor="guardrails",
                    resource_type="response",
                    resource_id=procedure_id or "unknown",
                    session_id=session_state.get("_session_id"),
                    procedure_id=procedure_id,
                    step_id=current_step,
                    metadata={"iteration": iteration + 1},
                )
            except Exception as e:
                logger.error("Rewrite generation failed: %s", e)
                break
        else:
            # No generate_fn or no rewrite hint — can't steer further
            break

    # If still invalid after all iterations, use safe fallback
    if (
        verification
        and verification.verdict == "INVALID"
        and verification.findings
        and any(f.severity == "error" for f in verification.findings)
    ):
        logger.warning(
            "Reasoning verification still INVALID after %d iterations, using safe fallback",
            max_iterations,
        )
        text = _SAFE_FALLBACK

    return text, pattern_violations, verification


def _run_verification(
    text: str,
    session_state: dict,
    procedure_id: Optional[str],
    current_step: Optional[str],
    policy: Any,
) -> Any:
    """Run reasoning + compliance verification on response text.

    Returns a VerificationResult or None if checks aren't applicable.
    """
    from .reasoning import VerificationResult, Finding

    settings = get_settings()
    findings: list[Finding] = []
    cited_rules: list[str] = []

    # Reasoning rails (Z3)
    if policy:
        engine = _get_reasoning_engine()
        result = engine.verify(text, policy, session_state, current_step)
        findings.extend(result.findings)
        cited_rules.extend(result.cited_rules)

    # Compliance rails
    if settings.compliance_enabled:
        checker = _get_compliance_checker()
        compliance_violations = checker.check_all(
            text, session_state, current_step, procedure_id,
        )
        for cv in compliance_violations:
            findings.append(Finding(
                rule_id=cv.rule_id,
                description=cv.description,
                severity=cv.severity,
                actual_value=cv.actual_value,
                expected_constraint=cv.expected,
            ))
            cited_rules.append(cv.rule_id)

    if not findings:
        return VerificationResult(
            verdict="NOT_APPLICABLE",
            explanation="No verifiable claims or applicable rules.",
        )

    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]

    if errors:
        hints = [f.description for f in errors]
        return VerificationResult(
            verdict="INVALID",
            findings=findings,
            cited_rules=cited_rules,
            explanation=f"Found {len(errors)} error(s): {'; '.join(hints)}",
            rewrite_hint=_build_combined_rewrite_hint(errors),
        )

    if warnings:
        return VerificationResult(
            verdict="SATISFIABLE",
            findings=findings,
            cited_rules=cited_rules,
            explanation=f"Response is plausible but has {len(warnings)} warning(s).",
        )

    return VerificationResult(
        verdict="VALID",
        findings=findings,
        cited_rules=cited_rules,
        explanation="All claims verified.",
    )


def _build_combined_rewrite_hint(errors: list) -> str:
    """Build a combined rewrite hint from error findings."""
    hints = []
    for err in errors:
        if hasattr(err, "expected_constraint") and err.expected_constraint:
            hints.append(f"- {err.description}. Expected: {err.expected_constraint}")
        else:
            hints.append(f"- {err.description}")
    return "\n".join(hints)


def _extract_session_facts(session_state: dict) -> str:
    """Extract relevant facts from session state for the rewrite prompt."""
    relevant_keys = [
        "order_id", "order_total", "order_date", "order_status",
        "customer_id", "customer_name", "refund_amount",
        "current_step", "current_procedure",
    ]
    facts = []
    for key in relevant_keys:
        val = session_state.get(key)
        if val is not None:
            facts.append(f"{key}={val}")
    return ", ".join(facts) if facts else "no session facts available"
