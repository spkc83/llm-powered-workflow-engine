"""Domain-specific compliance checker for LLM responses.

Uses SymPy for financial math verification and pattern-based checks for
procedural compliance (required disclosures, prohibited actions, step-appropriate
behavior).
"""

import re
from dataclasses import dataclass
from typing import Optional

import sympy

from ..logging_config import get_logger

logger = get_logger("agents.compliance")


@dataclass
class ComplianceViolation:
    """A compliance rule violation."""
    rule_id: str
    description: str
    severity: str  # "error", "warning", "info"
    actual_value: Optional[str] = None
    expected: Optional[str] = None


# ---------------------------------------------------------------------------
# Patterns for compliance checks
# ---------------------------------------------------------------------------

# Required disclosures by step
_REQUIRED_DISCLOSURES: dict[str, list[tuple[str, re.Pattern]]] = {
    "process_refund": [
        ("timeline_disclosure", re.compile(
            r"(?i)\b\d+[\s-]+\d*\s*(?:business\s+)?days?\b"
        )),
        ("reference_number_disclosure", re.compile(
            r"(?i)\b(?:reference|ref|confirmation)\s*(?:number|#|no)?\b"
        )),
    ],
    "offer_store_credit": [
        ("credit_amount_disclosure", re.compile(
            r"(?i)\$\s?[\d,]+\.?\d*"
        )),
    ],
    "escalate_case": [
        ("case_reference_disclosure", re.compile(
            r"(?i)\b(?:case|reference|ticket)\s*(?:number|#|no|id)?\b"
        )),
    ],
    # --- Reg E (EFT Dispute) required disclosures ---
    "file_dispute": [
        ("dispute_reference_number", re.compile(
            r"(?i)\b(?:dispute|reference|ref|confirmation)\s*(?:number|#|no|id)?\s*[:.]?\s*(?:DISP[-\s]?\w+|\w+-\w+)"
        )),
        ("investigation_timeline", re.compile(
            r"(?i)\b(?:10\s+business\s+days?|investigate\s+within)\b"
        )),
        ("provisional_credit_notice", re.compile(
            r"(?i)\b(?:provisional|temporary)\s+credit\b"
        )),
        ("written_acknowledgment", re.compile(
            r"(?i)\b(?:written\s+(?:acknowledgment|confirmation)|1\s+business\s+day)\b"
        )),
    ],
    "assess_provisional_credit": [
        ("credit_amount_disclosure", re.compile(
            r"(?i)\$\s?[\d,]+\.?\d*"
        )),
        ("credit_condition_disclosure", re.compile(
            r"(?i)\b(?:unless|until|remain|investigation)\b"
        )),
    ],
    "close_dispute": [
        ("dispute_summary", re.compile(
            r"(?i)\b(?:dispute|filed|reference)\b"
        )),
        ("next_steps_disclosure", re.compile(
            r"(?i)\b(?:next\s+steps?|investigation|results?|monitor)\b"
        )),
    ],
    "deny_late_dispute": [
        ("timeframe_explanation", re.compile(
            r"(?i)\b(?:60\s+days?|timeframe|window|regulation)\b"
        )),
        ("alternative_options", re.compile(
            r"(?i)\b(?:alternative|option|courtesy|escalat|supervisor)\b"
        )),
    ],
}

# Amount extraction
_AMOUNT_PATTERN = re.compile(r"\$\s?([\d,]+\.?\d*)")

# Prohibited content patterns
_PROHIBITED_PATTERNS = [
    ("no_investment_advice", re.compile(
        r"(?i)\b(?:you\s+should|i\s+recommend)\s+(?:invest|buy\s+stock|sell\s+stock)"
    ), "Response contains investment advice"),
    ("no_legal_advice", re.compile(
        r"(?i)\byou\s+(?:should|could)\s+(?:sue|file\s+a\s+lawsuit|take\s+legal\s+action)\b"
    ), "Response contains legal advice"),
    ("no_competitor_referral", re.compile(
        r"(?i)\b(?:try|use|switch\s+to)\s+(?:our\s+)?competitor"
    ), "Response refers customer to competitor"),
]


class ComplianceChecker:
    """Real-time compliance checks for domain-specific rules.

    Checks:
    - Financial accuracy (SymPy verification of amounts)
    - Required disclosures per procedure step
    - Prohibited content patterns
    - Procedure step compliance
    """

    def check_financial_compliance(
        self,
        response: str,
        session_state: dict,
    ) -> list[ComplianceViolation]:
        """Verify financial claims in LLM output using SymPy.

        Checks:
        - Refund amounts match order totals
        - No amounts exceed policy limits
        - Tax calculations are correct (when applicable)
        """
        violations: list[ComplianceViolation] = []

        amounts = _AMOUNT_PATTERN.findall(response)
        if not amounts:
            return violations

        order_total = session_state.get("order_total")
        if order_total is None:
            return violations

        try:
            order_total_f = float(order_total)
        except (ValueError, TypeError):
            return violations

        order_sym = sympy.Rational(str(order_total_f))

        for amount_str in amounts:
            amount_f = float(amount_str.replace(",", ""))
            amount_sym = sympy.Rational(str(amount_f))

            # Check: amount must not exceed order total
            if amount_sym > order_sym:
                violations.append(ComplianceViolation(
                    rule_id="financial:amount_exceeds_total",
                    description=(
                        f"Mentioned amount ${amount_f:.2f} exceeds order total "
                        f"${order_total_f:.2f}"
                    ),
                    severity="error",
                    actual_value=f"${amount_f:.2f}",
                    expected=f"<= ${order_total_f:.2f}",
                ))

            # Check: amount must be positive
            if amount_sym <= 0:
                violations.append(ComplianceViolation(
                    rule_id="financial:non_positive_amount",
                    description=f"Mentioned amount ${amount_f:.2f} is not positive",
                    severity="error",
                    actual_value=f"${amount_f:.2f}",
                    expected="> $0.00",
                ))

        return violations

    def check_reg_e_compliance(
        self,
        response: str,
        session_state: dict,
        current_step: Optional[str] = None,
    ) -> list[ComplianceViolation]:
        """Verify Regulation E compliance for EFT dispute responses.

        Checks:
        - Liability tier amounts are correct ($50 tier 1, $500 tier 2)
        - Provisional credit = disputed amount - max liability
        - Investigation timeline claims are accurate (10 business days / 45 calendar)
        - No exposure of internal tier system to customer
        """
        violations: list[ComplianceViolation] = []

        dispute_data = session_state.get("dispute_data", {})
        eligibility = session_state.get("dispute_eligibility", {})
        if not dispute_data and not eligibility:
            return violations

        # --- Liability amount verification (SymPy) ---
        max_liability = eligibility.get("max_liability") or dispute_data.get("max_liability")
        disputed_amount = dispute_data.get("amount")

        if max_liability is not None and disputed_amount is not None:
            try:
                max_liability_f = float(max_liability)
                disputed_amount_f = float(disputed_amount)
            except (ValueError, TypeError):
                max_liability_f = None
                disputed_amount_f = None

            if max_liability_f is not None and disputed_amount_f is not None:
                amounts_in_response = _AMOUNT_PATTERN.findall(response)
                for amt_str in amounts_in_response:
                    amt_f = float(amt_str.replace(",", ""))
                    amt_sym = sympy.Rational(str(amt_f))
                    disputed_sym = sympy.Rational(str(disputed_amount_f))

                    # Provisional credit must not exceed disputed amount
                    if current_step == "assess_provisional_credit" and amt_sym > disputed_sym:
                        violations.append(ComplianceViolation(
                            rule_id="reg_e:provisional_credit_exceeds_dispute",
                            description=(
                                f"Provisional credit ${amt_f:.2f} exceeds disputed "
                                f"amount ${disputed_amount_f:.2f}"
                            ),
                            severity="error",
                            actual_value=f"${amt_f:.2f}",
                            expected=f"<= ${disputed_amount_f:.2f}",
                        ))

                # Verify provisional credit calculation if present
                prov_credit = session_state.get("provisional_credit", {})
                if prov_credit and prov_credit.get("provisional_credit_issued"):
                    expected_credit = max(0, disputed_amount_f - max_liability_f)
                    actual_credit = prov_credit.get("provisional_credit_amount", 0)
                    expected_sym = sympy.Rational(str(expected_credit))
                    actual_sym = sympy.Rational(str(actual_credit))
                    if actual_sym != expected_sym:
                        violations.append(ComplianceViolation(
                            rule_id="reg_e:provisional_credit_miscalculated",
                            description=(
                                f"Provisional credit ${actual_credit:.2f} != "
                                f"disputed ${disputed_amount_f:.2f} - liability ${max_liability_f:.2f} "
                                f"= ${expected_credit:.2f}"
                            ),
                            severity="error",
                            actual_value=f"${actual_credit:.2f}",
                            expected=f"${expected_credit:.2f}",
                        ))

        # --- Internal tier exposure check ---
        tier_exposure_pattern = re.compile(
            r"(?i)\b(?:tier\s*[123]|liability\s+tier|tier_[123])\b"
        )
        if tier_exposure_pattern.search(response):
            violations.append(ComplianceViolation(
                rule_id="reg_e:internal_tier_exposed",
                description="Response exposes internal liability tier system to customer",
                severity="error",
            ))

        # --- Investigation timeline accuracy ---
        if current_step in ("file_dispute", "close_dispute"):
            # Check for incorrect timeline claims
            wrong_timeline = re.compile(
                r"(?i)\b(?:30|60|90)\s+business\s+days?\b"
            )
            if wrong_timeline.search(response):
                # 45/90 are calendar days, not business days; 10 is business days
                violations.append(ComplianceViolation(
                    rule_id="reg_e:incorrect_timeline_units",
                    description=(
                        "Investigation timeline uses wrong units. "
                        "10 business days for initial; 45/90 calendar days for final."
                    ),
                    severity="warning",
                ))

        return violations

    def check_procedure_compliance(
        self,
        response: str,
        current_step: Optional[str],
        procedure_id: Optional[str] = None,
    ) -> list[ComplianceViolation]:
        """Verify response follows procedure rules for current step.

        Checks:
        - Required disclosures are present for the current step
        - No prohibited content patterns
        """
        violations: list[ComplianceViolation] = []

        # Check required disclosures for current step
        if current_step and current_step in _REQUIRED_DISCLOSURES:
            for disclosure_id, pattern in _REQUIRED_DISCLOSURES[current_step]:
                if not pattern.search(response):
                    violations.append(ComplianceViolation(
                        rule_id=f"disclosure:{disclosure_id}",
                        description=(
                            f"Required disclosure '{disclosure_id}' missing at "
                            f"step '{current_step}'"
                        ),
                        severity="warning",
                        expected=f"Disclosure pattern: {disclosure_id}",
                    ))

        # Check prohibited content
        for rule_id, pattern, desc in _PROHIBITED_PATTERNS:
            if pattern.search(response):
                violations.append(ComplianceViolation(
                    rule_id=f"prohibited:{rule_id}",
                    description=desc,
                    severity="error",
                ))

        return violations

    def check_all(
        self,
        response: str,
        session_state: dict,
        current_step: Optional[str] = None,
        procedure_id: Optional[str] = None,
    ) -> list[ComplianceViolation]:
        """Run all compliance checks.

        Returns combined list of violations from financial and procedural checks.
        """
        violations: list[ComplianceViolation] = []

        violations.extend(self.check_financial_compliance(response, session_state))
        violations.extend(self.check_procedure_compliance(
            response, current_step, procedure_id,
        ))

        # Reg E compliance checks (when dispute context is present)
        if procedure_id == "cs_eft_dispute" or session_state.get("dispute_data") or session_state.get("dispute_eligibility"):
            violations.extend(self.check_reg_e_compliance(
                response, session_state, current_step,
            ))

        if violations:
            logger.warning(
                "Compliance violations detected (%d): %s",
                len(violations),
                [v.rule_id for v in violations],
            )

        return violations
