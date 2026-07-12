"""Tests for the automated reasoning engine, compliance checker, and behavior steering."""

import pytest
from datetime import datetime, timedelta, timezone

from workflow_engine.agents.reasoning import (
    ReasoningEngine,
    build_policy_from_procedure,
    extract_claims,
)
from workflow_engine.agents.compliance import ComplianceChecker


# ---------------------------------------------------------------------------
# Fixtures — sample procedure and session state
# ---------------------------------------------------------------------------

@pytest.fixture
def refund_procedure():
    """A minimal refund procedure definition for testing."""
    return {
        "id": "cs_refund",
        "name": "Customer Service - Refund Request",
        "steps": [
            {
                "id": "greet_and_collect",
                "instruction": "Greet the customer.",
                "action": "collect_info",
                "next_step": "lookup_order",
            },
            {
                "id": "lookup_order",
                "instruction": "Look up the order.",
                "action": "tool_call",
                "tool": "lookup_order",
                "on_success": "check_eligibility",
                "on_failure": "order_not_found",
            },
            {
                "id": "check_eligibility",
                "instruction": "Check refund eligibility.",
                "action": "evaluate",
                "conditions": [
                    {
                        "if": "order_date within 30 days AND order_status in [delivered, shipped] AND category not in non_refundable_list",
                        "next_step": "process_refund",
                    },
                    {
                        "if": "order_date outside 30 days",
                        "next_step": "deny_refund_window",
                    },
                    {
                        "if": "order_status == processing",
                        "next_step": "cancel_order",
                    },
                ],
            },
            {
                "id": "process_refund",
                "instruction": "Process the refund.",
                "action": "tool_call",
                "tool": "issue_refund",
                "on_success": "close_case",
                "on_failure": "escalate_case",
            },
            {
                "id": "deny_refund_window",
                "instruction": "Deny refund, offer alternatives.",
                "action": "inform",
                "options": [
                    {"label": "Store credit", "next_step": "offer_store_credit"},
                    {"label": "Escalate", "next_step": "escalate_case"},
                ],
            },
            {
                "id": "offer_store_credit",
                "instruction": "Offer store credit.",
                "action": "tool_call",
                "tool": "issue_store_credit",
                "on_success": "close_case",
                "on_failure": "escalate_case",
            },
            {
                "id": "cancel_order",
                "instruction": "Cancel order in processing.",
                "action": "tool_call",
                "tool": "update_case_status",
                "on_success": "close_case",
                "on_failure": "escalate_case",
            },
            {
                "id": "escalate_case",
                "instruction": "Escalate to supervisor.",
                "action": "tool_call",
                "tool": "escalate_to_supervisor",
                "on_success": "close_case",
                "on_failure": "close_case",
            },
            {
                "id": "order_not_found",
                "instruction": "Order not found.",
                "action": "inform",
                "next_step": "greet_and_collect",
            },
            {
                "id": "close_case",
                "instruction": "Close the case.",
                "action": "tool_call",
                "tool": "update_case_status",
                "on_success": "end",
                "on_failure": "end",
                "next_step": "end",
            },
        ],
    }


@pytest.fixture
def eligible_session_state():
    """Session state for an eligible refund (within 30 days, delivered)."""
    order_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
    return {
        "customer_id": "CUST-123",
        "order_id": "ORD-456",
        "order_date": order_date,
        "order_status": "delivered",
        "order_total": 79.99,
        "is_refundable_category": True,
        "_session_id": "test-session-1",
    }


@pytest.fixture
def ineligible_session_state():
    """Session state for an ineligible refund (outside 30 days)."""
    order_date = (datetime.now(timezone.utc) - timedelta(days=45)).strftime("%Y-%m-%d")
    return {
        "customer_id": "CUST-789",
        "order_id": "ORD-012",
        "order_date": order_date,
        "order_status": "delivered",
        "order_total": 149.99,
        "is_refundable_category": True,
        "_session_id": "test-session-2",
    }


@pytest.fixture
def engine():
    return ReasoningEngine()


@pytest.fixture
def compliance_checker():
    return ComplianceChecker()


# ===========================================================================
# Test: Claim Extraction
# ===========================================================================


class TestClaimExtraction:
    def test_extracts_dollar_amounts(self):
        claims = extract_claims("Your refund of $79.99 has been processed.")
        assert 79.99 in claims["mentioned_amounts"]

    def test_extracts_multiple_amounts(self):
        claims = extract_claims("The order was $150.00 and the refund is $79.99.")
        assert len(claims["mentioned_amounts"]) == 2

    def test_extracts_day_counts(self):
        claims = extract_claims("Refund will arrive in 5-7 business days.")
        assert 5 in claims["mentioned_days"]
        assert 7 in claims["mentioned_days"]

    def test_detects_refund_approval(self):
        claims = extract_claims("Your refund has been approved and processed.")
        assert claims.get("claims_refund_approved") is True

    def test_detects_refund_denial(self):
        claims = extract_claims("Unfortunately your order is not eligible for a refund.")
        assert claims.get("claims_refund_denied") is True

    def test_detects_store_credit(self):
        claims = extract_claims("I can offer you store credit instead.")
        assert claims.get("claims_store_credit") is True

    def test_detects_escalation(self):
        claims = extract_claims("I'll escalate this to a supervisor for you.")
        assert claims.get("claims_escalation") is True

    def test_no_claims_from_generic_text(self):
        claims = extract_claims("Hello, how can I help you today?")
        assert len(claims) == 0


# ===========================================================================
# Test: Policy Extraction from YAML
# ===========================================================================


class TestPolicyExtraction:
    def test_builds_policy_from_procedure(self, refund_procedure):
        policy = build_policy_from_procedure(refund_procedure)
        assert policy.procedure_id == "cs_refund"
        assert len(policy.variables) > 0
        assert len(policy.rules) > 0

    def test_policy_has_eligibility_rules(self, refund_procedure):
        policy = build_policy_from_procedure(refund_procedure)
        eligibility_rules = [r for r in policy.rules if "check_eligibility" in r.source_step]
        assert len(eligibility_rules) >= 2  # within 30 days + outside 30 days

    def test_policy_has_universal_rules(self, refund_procedure):
        policy = build_policy_from_procedure(refund_procedure)
        universal_rules = [r for r in policy.rules if r.source_step == "*"]
        assert len(universal_rules) >= 2  # refund <= total, refund > 0

    def test_policy_has_z3_variables(self, refund_procedure):
        policy = build_policy_from_procedure(refund_procedure)
        assert "order_age_days" in policy.variables
        assert "order_total" in policy.variables
        assert "refund_amount" in policy.variables
        assert "order_status" in policy.variables


# ===========================================================================
# Test: Reasoning Engine Verification
# ===========================================================================


class TestReasoningEngine:
    def test_valid_refund_response_passes(self, engine, refund_procedure, eligible_session_state):
        policy = build_policy_from_procedure(refund_procedure)
        result = engine.verify(
            "Your refund of $79.99 has been approved and will be credited within 5-7 business days.",
            policy,
            eligible_session_state,
            current_step="process_refund",
        )
        assert result.verdict in ("VALID", "SATISFIABLE", "NOT_APPLICABLE")
        # Should NOT be INVALID
        assert result.verdict != "INVALID"

    def test_invalid_refund_outside_window_detected(self, engine, refund_procedure, ineligible_session_state):
        policy = build_policy_from_procedure(refund_procedure)
        result = engine.verify(
            "Great news! Your refund of $149.99 has been approved and processed.",
            policy,
            ineligible_session_state,
            current_step="process_refund",
        )
        # Should detect that the order is outside the 30-day window
        assert result.verdict == "INVALID"
        assert len(result.findings) > 0
        assert any("eligible" in f.description.lower() or "window" in f.description.lower()
                    for f in result.findings)

    def test_wrong_amount_detected(self, engine, refund_procedure, eligible_session_state):
        policy = build_policy_from_procedure(refund_procedure)
        # Claim $200 refund when order total is $79.99
        result = engine.verify(
            "Your refund of $200.00 has been approved.",
            policy,
            eligible_session_state,
            current_step="process_refund",
        )
        assert result.verdict == "INVALID"
        assert any("exceeds" in f.description.lower() for f in result.findings)

    def test_satisfiable_when_missing_info(self, engine, refund_procedure):
        policy = build_policy_from_procedure(refund_procedure)
        # No order details in session state
        result = engine.verify(
            "Your refund has been approved.",
            policy,
            {"customer_id": "CUST-001"},
            current_step="process_refund",
        )
        # Without grounding data, should be NOT_APPLICABLE or SATISFIABLE
        assert result.verdict in ("NOT_APPLICABLE", "SATISFIABLE", "VALID")

    def test_no_claims_returns_not_applicable(self, engine, refund_procedure, eligible_session_state):
        policy = build_policy_from_procedure(refund_procedure)
        result = engine.verify(
            "Hello! How can I help you today?",
            policy,
            eligible_session_state,
        )
        assert result.verdict == "NOT_APPLICABLE"

    def test_step_compliance_warning(self, engine, refund_procedure, eligible_session_state):
        policy = build_policy_from_procedure(refund_procedure)
        # Claim refund approved at the wrong step (greet_and_collect)
        result = engine.verify(
            "Your refund of $79.99 has been approved!",
            policy,
            eligible_session_state,
            current_step="greet_and_collect",
        )
        # Should have a step compliance warning
        step_findings = [f for f in result.findings if "wrong_step" in f.rule_id]
        assert len(step_findings) > 0


# ===========================================================================
# Test: Compliance Checker
# ===========================================================================


class TestComplianceChecker:
    def test_financial_amount_exceeds_total(self, compliance_checker):
        violations = compliance_checker.check_financial_compliance(
            "Your refund of $200.00 has been processed.",
            {"order_total": 79.99},
        )
        assert any(v.rule_id == "financial:amount_exceeds_total" for v in violations)

    def test_financial_amount_within_total(self, compliance_checker):
        violations = compliance_checker.check_financial_compliance(
            "Your refund of $79.99 has been processed.",
            {"order_total": 79.99},
        )
        assert not any(v.rule_id == "financial:amount_exceeds_total" for v in violations)

    def test_missing_timeline_disclosure(self, compliance_checker):
        violations = compliance_checker.check_procedure_compliance(
            "Your refund has been approved!",
            current_step="process_refund",
        )
        # Should detect missing timeline disclosure
        assert any("timeline_disclosure" in v.rule_id for v in violations)

    def test_timeline_disclosure_present(self, compliance_checker):
        violations = compliance_checker.check_procedure_compliance(
            "Your refund has been approved! Expect it within 5-7 business days. Reference number: REF-123.",
            current_step="process_refund",
        )
        # Timeline and reference disclosures should be satisfied
        assert not any("timeline_disclosure" in v.rule_id for v in violations)
        assert not any("reference_number_disclosure" in v.rule_id for v in violations)

    def test_prohibited_investment_advice(self, compliance_checker):
        violations = compliance_checker.check_procedure_compliance(
            "You should invest in index funds for better returns.",
            current_step="close_case",
        )
        assert any("investment_advice" in v.rule_id for v in violations)

    def test_check_all_combines_results(self, compliance_checker):
        violations = compliance_checker.check_all(
            "Your refund of $200.00 has been approved!",
            session_state={"order_total": 79.99},
            current_step="process_refund",
        )
        # Should have both financial and disclosure violations
        assert len(violations) >= 2


# ===========================================================================
# Test: Behavior Steering
# ===========================================================================


class TestBehaviorSteering:
    @pytest.mark.asyncio
    async def test_valid_response_passes_through(self):
        """Valid response should pass through without modification."""
        from workflow_engine.agents.guardrails import steer_response

        text = "Hello, how can I help you today?"
        result_text, violations, verification = await steer_response(
            text=text,
            session_state={},
            procedure_id=None,
        )
        assert result_text == text
        assert len(violations) == 0

    @pytest.mark.asyncio
    async def test_pattern_rails_still_work(self):
        """Pattern rails should still redact internal data."""
        from workflow_engine.agents.guardrails import steer_response

        text = "The step_id: check_eligibility is active now."
        result_text, violations, verification = await steer_response(
            text=text,
            session_state={},
        )
        assert "REDACTED" in result_text
        assert len(violations) > 0

    @pytest.mark.asyncio
    async def test_rewrite_loop_with_generate_fn(self, refund_procedure, ineligible_session_state):
        """If generate_fn is provided, should attempt rewrite on INVALID."""
        from workflow_engine.agents.guardrails import steer_response

        rewrite_count = {"count": 0}

        async def mock_generate(prompt: str) -> str:
            rewrite_count["count"] += 1
            # Return a corrected response on rewrite
            return (
                "I'm sorry, but your order falls outside our 30-day return window "
                "and is not eligible for a standard refund. However, I can offer you "
                "store credit for the full amount."
            )

        text = "Great news! Your refund of $149.99 has been approved and processed!"
        result_text, violations, verification = await steer_response(
            text=text,
            session_state=ineligible_session_state,
            procedure_id="cs_refund",
            current_step="process_refund",
            procedure_def=refund_procedure,
            generate_fn=mock_generate,
            max_iterations=2,
        )
        # Should have attempted at least one rewrite
        assert rewrite_count["count"] >= 1

    @pytest.mark.asyncio
    async def test_max_iterations_returns_fallback(self, refund_procedure, ineligible_session_state):
        """If still invalid after max iterations, should return safe fallback."""
        from workflow_engine.agents.guardrails import steer_response

        async def always_invalid_generate(prompt: str) -> str:
            # Always return an invalid response
            return "Your refund of $999.99 has been approved!"

        text = "Your refund of $999.99 has been approved!"
        result_text, violations, verification = await steer_response(
            text=text,
            session_state=ineligible_session_state,
            procedure_id="cs_refund",
            current_step="process_refund",
            procedure_def=refund_procedure,
            generate_fn=always_invalid_generate,
            max_iterations=2,
        )
        # Should fall back to safe response
        assert "unable to provide" in result_text.lower() or "specialist" in result_text.lower()
