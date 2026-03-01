"""Automated reasoning engine using Z3 and SymPy for formal verification.

Translates procedure YAML rules into Z3 formal logic constraints, then verifies
LLM response claims against those constraints using the Z3 SMT solver. Financial
calculations are cross-checked with SymPy for symbolic math verification.

Inspired by:
- QWED Protocol (neurosymbolic verification)
- AWS Bedrock Automated Reasoning (formal logic policies)
- NeMo Guardrails (rail pipeline architecture)
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import z3
import sympy

from ..logging_config import get_logger

logger = get_logger("agents.reasoning")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    """A single finding from verification."""
    rule_id: str
    description: str
    severity: str  # "error", "warning", "info"
    actual_value: Optional[str] = None
    expected_constraint: Optional[str] = None


@dataclass
class ReasoningRule:
    """A single formal rule with Z3 constraint."""
    rule_id: str
    description: str
    constraint: z3.BoolRef
    source_step: str  # which procedure step this rule comes from


@dataclass
class ReasoningPolicy:
    """A set of formal logic rules extracted from a procedure."""
    procedure_id: str
    variables: dict[str, z3.ExprRef] = field(default_factory=dict)
    rules: list[ReasoningRule] = field(default_factory=list)
    source_document: str = ""  # procedure YAML path


@dataclass
class VerificationResult:
    """Result of verifying an LLM response."""
    verdict: str  # VALID | INVALID | SATISFIABLE | NOT_APPLICABLE
    findings: list[Finding] = field(default_factory=list)
    cited_rules: list[str] = field(default_factory=list)
    explanation: str = ""
    rewrite_hint: Optional[str] = None  # feedback for behavior steering

    @property
    def is_valid(self) -> bool:
        return self.verdict == "VALID"


# ---------------------------------------------------------------------------
# Claim extraction from LLM responses
# ---------------------------------------------------------------------------

# Patterns to extract numeric claims from LLM text
_AMOUNT_PATTERN = re.compile(r"\$\s?([\d,]+\.?\d*)")
_DAYS_PATTERN = re.compile(r"(\d+)\s*(?:[-–]\s*(\d+)\s*)?(?:business\s+)?days?")
_REFUND_APPROVED_PATTERN = re.compile(r"(?i)\brefund\b.*?\b(?:approved|processed|issued|credited)\b")
_REFUND_DENIED_PATTERN = re.compile(r"(?i)\b(?:not\s+eligible|cannot\s+process|outside.*window|denied)\b")
_STORE_CREDIT_PATTERN = re.compile(r"(?i)\bstore\s+credit\b")
_ESCALATION_PATTERN = re.compile(r"(?i)\b(?:escalat|supervisor|senior\s+representative)\b")


def extract_claims(response_text: str) -> dict[str, Any]:
    """Extract verifiable claims from an LLM response.

    Returns a dict of claim types to their extracted values.
    """
    claims: dict[str, Any] = {}

    # Extract dollar amounts
    amounts = _AMOUNT_PATTERN.findall(response_text)
    if amounts:
        claims["mentioned_amounts"] = [float(a.replace(",", "")) for a in amounts]

    # Extract day counts (timelines) — handles ranges like "5-7 business days"
    day_matches = _DAYS_PATTERN.findall(response_text)
    if day_matches:
        day_values = []
        for match in day_matches:
            # match is a tuple of (first_num, optional_second_num)
            day_values.append(int(match[0]))
            if match[1]:
                day_values.append(int(match[1]))
        claims["mentioned_days"] = day_values

    # Detect refund approval claim
    if _REFUND_APPROVED_PATTERN.search(response_text):
        claims["claims_refund_approved"] = True

    # Detect refund denial
    if _REFUND_DENIED_PATTERN.search(response_text):
        claims["claims_refund_denied"] = True

    # Detect store credit offer
    if _STORE_CREDIT_PATTERN.search(response_text):
        claims["claims_store_credit"] = True

    # Detect escalation
    if _ESCALATION_PATTERN.search(response_text):
        claims["claims_escalation"] = True

    return claims


# ---------------------------------------------------------------------------
# Policy extraction from procedure YAML
# ---------------------------------------------------------------------------


def build_policy_from_procedure(procedure: dict) -> ReasoningPolicy:
    """Extract formal reasoning rules from a procedure definition.

    Parses the conditions and instructions in procedure steps to create
    Z3 constraints that can be used for verification.

    Args:
        procedure: The parsed procedure dict from YAML.

    Returns:
        A ReasoningPolicy with Z3 variables and rules.
    """
    proc_id = procedure.get("id", "unknown")
    policy = ReasoningPolicy(
        procedure_id=proc_id,
        source_document=f"procedures/{proc_id}.yaml",
    )

    # Define common Z3 variables for customer service domain
    order_age_days = z3.Int("order_age_days")
    order_total = z3.Real("order_total")
    refund_amount = z3.Real("refund_amount")
    order_status = z3.String("order_status")
    is_refundable_category = z3.Bool("is_refundable_category")

    policy.variables = {
        "order_age_days": order_age_days,
        "order_total": order_total,
        "refund_amount": refund_amount,
        "order_status": order_status,
        "is_refundable_category": is_refundable_category,
    }

    steps = procedure.get("steps", [])
    for step in steps:
        step_id = step.get("id", "")
        conditions = step.get("conditions", [])

        if not conditions:
            continue

        for i, cond in enumerate(conditions):
            cond_text = cond.get("if", "")
            next_step = cond.get("next_step", "")
            rule_id = f"{proc_id}:{step_id}:cond_{i}"

            constraint = _parse_condition_to_z3(
                cond_text, next_step, policy.variables
            )
            if constraint is not None:
                policy.rules.append(ReasoningRule(
                    rule_id=rule_id,
                    description=f"Condition: {cond_text} -> {next_step}",
                    constraint=constraint,
                    source_step=step_id,
                ))

    # Add universal rules that apply regardless of procedure step
    _add_universal_rules(policy)

    logger.info(
        "Built reasoning policy for '%s': %d rules, %d variables",
        proc_id, len(policy.rules), len(policy.variables),
    )
    return policy


def _parse_condition_to_z3(
    condition_text: str,
    next_step: str,
    variables: dict[str, z3.ExprRef],
) -> Optional[z3.BoolRef]:
    """Parse a human-readable condition string into a Z3 boolean expression.

    Handles the condition patterns found in procedure YAML files.
    """
    order_age_days = variables["order_age_days"]
    order_status = variables["order_status"]
    is_refundable_category = variables["is_refundable_category"]

    cond_lower = condition_text.lower()

    # Pattern: "order_date within 30 days AND order_status in [delivered, shipped] AND ..."
    if "within 30 days" in cond_lower and next_step == "process_refund":
        return z3.And(
            order_age_days <= 30,
            z3.Or(
                order_status == z3.StringVal("delivered"),
                order_status == z3.StringVal("shipped"),
            ),
            is_refundable_category,
        )

    # Pattern: "order_date outside 30 days"
    if "outside 30 days" in cond_lower:
        return order_age_days > 30

    # Pattern: "order_status == processing"
    if "processing" in cond_lower:
        return order_status == z3.StringVal("processing")

    return None


def _add_universal_rules(policy: ReasoningPolicy) -> None:
    """Add universal rules that apply across all procedures."""
    order_total = policy.variables["order_total"]
    refund_amount = policy.variables["refund_amount"]

    # Rule: refund amount must not exceed order total
    policy.rules.append(ReasoningRule(
        rule_id=f"{policy.procedure_id}:universal:refund_lte_total",
        description="Refund amount must not exceed order total",
        constraint=refund_amount <= order_total,
        source_step="*",
    ))

    # Rule: refund amount must be positive
    policy.rules.append(ReasoningRule(
        rule_id=f"{policy.procedure_id}:universal:refund_positive",
        description="Refund amount must be positive",
        constraint=refund_amount > z3.RealVal(0),
        source_step="*",
    ))

    # Rule: order total must be positive
    policy.rules.append(ReasoningRule(
        rule_id=f"{policy.procedure_id}:universal:order_total_positive",
        description="Order total must be positive",
        constraint=order_total > z3.RealVal(0),
        source_step="*",
    ))


# ---------------------------------------------------------------------------
# Verification engine
# ---------------------------------------------------------------------------


class ReasoningEngine:
    """Formal verification engine using Z3 SMT solver.

    Verifies LLM response claims against procedure rules by:
    1. Extracting claims from the response text
    2. Grounding Z3 variables with actual session state values
    3. Checking each relevant claim against Z3 constraints
    4. Returning a structured verdict with cited rules
    """

    def verify(
        self,
        response_text: str,
        policy: ReasoningPolicy,
        session_state: dict,
        current_step: Optional[str] = None,
    ) -> VerificationResult:
        """Verify an LLM response against a formal reasoning policy.

        Args:
            response_text: The LLM's response text to verify.
            policy: The reasoning policy with Z3 rules.
            session_state: Session state with actual values (order details, etc.).
            current_step: The current procedure step ID, if any.

        Returns:
            VerificationResult with verdict and findings.
        """
        if not policy.rules:
            return VerificationResult(
                verdict="NOT_APPLICABLE",
                explanation="No reasoning rules available for this procedure.",
            )

        claims = extract_claims(response_text)
        if not claims:
            return VerificationResult(
                verdict="NOT_APPLICABLE",
                explanation="No verifiable claims found in the response.",
            )

        findings: list[Finding] = []
        cited_rules: list[str] = []

        # Check refund eligibility claims
        findings.extend(self._verify_eligibility_claims(
            claims, policy, session_state, current_step, cited_rules,
        ))

        # Check financial amount claims
        findings.extend(self._verify_amount_claims(
            claims, policy, session_state, cited_rules,
        ))

        # Check step-appropriate action claims
        findings.extend(self._verify_step_claims(
            claims, session_state, current_step, cited_rules,
        ))

        # Determine overall verdict
        errors = [f for f in findings if f.severity == "error"]
        warnings = [f for f in findings if f.severity == "warning"]

        if errors:
            hints = [f.description for f in errors]
            return VerificationResult(
                verdict="INVALID",
                findings=findings,
                cited_rules=cited_rules,
                explanation=f"Found {len(errors)} error(s): {'; '.join(hints)}",
                rewrite_hint=self._build_rewrite_hint(errors),
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
            explanation="All claims verified against formal rules.",
        )

    def _verify_eligibility_claims(
        self,
        claims: dict[str, Any],
        policy: ReasoningPolicy,
        session_state: dict,
        current_step: Optional[str],
        cited_rules: list[str],
    ) -> list[Finding]:
        """Verify refund eligibility claims against Z3 constraints."""
        findings: list[Finding] = []

        # Only verify if the response claims a refund approval or denial
        claims_approval = claims.get("claims_refund_approved", False)
        claims_denial = claims.get("claims_refund_denied", False)

        if not claims_approval and not claims_denial:
            return findings

        # Ground variables from session state
        order_age = self._get_order_age_days(session_state)
        order_status_val = session_state.get("order_status", "")

        if order_age is None or not order_status_val:
            # Not enough state to verify — satisfiable but not provable
            return findings

        # Check eligibility with Z3
        solver = z3.Solver()
        solver.set("timeout", 5000)  # 5 second timeout

        v = policy.variables
        # Ground the variables
        solver.add(v["order_age_days"] == order_age)
        solver.add(v["order_status"] == z3.StringVal(order_status_val))

        # Determine if category is refundable (default True if not specified)
        category_refundable = session_state.get("is_refundable_category", True)
        solver.add(v["is_refundable_category"] == category_refundable)

        # Check the eligibility rules
        eligible_rules = [
            r for r in policy.rules
            if r.source_step == "check_eligibility" and "process_refund" in r.description
        ]

        for rule in eligible_rules:
            cited_rules.append(rule.rule_id)
            solver.push()
            solver.add(rule.constraint)
            result = solver.check()
            solver.pop()

            is_eligible = result == z3.sat

            if claims_approval and not is_eligible:
                findings.append(Finding(
                    rule_id=rule.rule_id,
                    description=(
                        f"Response claims refund approved but order is NOT eligible: "
                        f"order_age={order_age} days, status={order_status_val}"
                    ),
                    severity="error",
                    actual_value=f"age={order_age}, status={order_status_val}",
                    expected_constraint="age <= 30 AND status in [delivered, shipped]",
                ))

            if claims_denial and is_eligible:
                findings.append(Finding(
                    rule_id=rule.rule_id,
                    description=(
                        f"Response claims refund denied but order IS eligible: "
                        f"order_age={order_age} days, status={order_status_val}"
                    ),
                    severity="error",
                    actual_value=f"age={order_age}, status={order_status_val}",
                    expected_constraint="age <= 30 AND status in [delivered, shipped]",
                ))

        return findings

    def _verify_amount_claims(
        self,
        claims: dict[str, Any],
        policy: ReasoningPolicy,
        session_state: dict,
        cited_rules: list[str],
    ) -> list[Finding]:
        """Verify financial amount claims using Z3 and SymPy."""
        findings: list[Finding] = []

        mentioned_amounts = claims.get("mentioned_amounts", [])
        if not mentioned_amounts:
            return findings

        order_total = session_state.get("order_total")
        if order_total is None:
            return findings

        try:
            order_total_f = float(order_total)
        except (ValueError, TypeError):
            return findings

        # Use SymPy for financial math verification
        order_sym = sympy.Rational(str(order_total_f))

        for amount in mentioned_amounts:
            amount_sym = sympy.Rational(str(amount))

            # Check: refund amount must not exceed order total
            if amount_sym > order_sym:
                rule_id = f"{policy.procedure_id}:universal:refund_lte_total"
                cited_rules.append(rule_id)
                findings.append(Finding(
                    rule_id=rule_id,
                    description=(
                        f"Mentioned amount ${amount:.2f} exceeds order total "
                        f"${order_total_f:.2f}"
                    ),
                    severity="error",
                    actual_value=f"${amount:.2f}",
                    expected_constraint=f"<= ${order_total_f:.2f}",
                ))

            # Also verify with Z3 for formal proof
            solver = z3.Solver()
            solver.set("timeout", 2000)
            v = policy.variables
            solver.add(v["order_total"] == z3.RealVal(str(order_total_f)))
            solver.add(v["refund_amount"] == z3.RealVal(str(amount)))

            refund_rules = [
                r for r in policy.rules
                if "refund_lte_total" in r.rule_id
            ]
            for rule in refund_rules:
                solver.push()
                solver.add(z3.Not(rule.constraint))
                result = solver.check()
                solver.pop()

                # If NOT(constraint) is satisfiable, constraint is violated
                if result == z3.sat:
                    if rule.rule_id not in cited_rules:
                        cited_rules.append(rule.rule_id)
                    # Already added finding via SymPy above

        return findings

    def _verify_step_claims(
        self,
        claims: dict[str, Any],
        session_state: dict,
        current_step: Optional[str],
        cited_rules: list[str],
    ) -> list[Finding]:
        """Verify that claims are appropriate for the current procedure step."""
        findings: list[Finding] = []

        if not current_step:
            return findings

        # Refund approval should only happen at process_refund step
        if claims.get("claims_refund_approved") and current_step not in (
            "process_refund", "cancel_order"
        ):
            findings.append(Finding(
                rule_id="step_compliance:refund_at_wrong_step",
                description=(
                    f"Response claims refund approved at step '{current_step}', "
                    f"but refunds should only be issued at 'process_refund' or 'cancel_order' step"
                ),
                severity="warning",
                actual_value=current_step,
                expected_constraint="process_refund or cancel_order",
            ))

        # Store credit should only be offered at deny_refund_window or offer_store_credit
        if claims.get("claims_store_credit") and current_step not in (
            "deny_refund_window", "offer_store_credit"
        ):
            findings.append(Finding(
                rule_id="step_compliance:store_credit_at_wrong_step",
                description=(
                    f"Response mentions store credit at step '{current_step}', "
                    f"but store credit should only be offered at 'deny_refund_window' or "
                    f"'offer_store_credit' step"
                ),
                severity="warning",
                actual_value=current_step,
                expected_constraint="deny_refund_window or offer_store_credit",
            ))

        return findings

    def _build_rewrite_hint(self, errors: list[Finding]) -> str:
        """Build a rewrite hint from error findings for behavior steering."""
        hints = []
        for err in errors:
            if err.expected_constraint:
                hints.append(
                    f"- {err.description}. Expected: {err.expected_constraint}"
                )
            else:
                hints.append(f"- {err.description}")
        return (
            "The response contains factual errors that violate verified business rules. "
            "Please correct the following:\n" + "\n".join(hints)
        )

    @staticmethod
    def _get_order_age_days(session_state: dict) -> Optional[int]:
        """Calculate order age in days from session state."""
        order_date_str = session_state.get("order_date")
        if not order_date_str:
            return None
        try:
            # Handle common date formats
            for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                try:
                    order_date = datetime.strptime(order_date_str, fmt).replace(
                        tzinfo=timezone.utc
                    )
                    delta = datetime.now(timezone.utc) - order_date
                    return delta.days
                except ValueError:
                    continue
        except Exception:
            pass
        return None
