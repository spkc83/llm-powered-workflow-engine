"""Tests for Regulation E compliance checks and dispute tools.

Covers:
- Reg E compliance rules in the compliance checker
- Dispute tool logic (liability tiers, eligibility, provisional credit)
- Required disclosures for dispute procedure steps
- Financial math verification with SymPy
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from workflow_engine.agents.compliance import ComplianceChecker, ComplianceViolation
from workflow_engine.tools.dispute_tools import (
    _calculate_liability_tier,
    _is_eft_covered,
)


# ---------------------------------------------------------------------------
# Liability tier calculation
# ---------------------------------------------------------------------------

class TestLiabilityTiers:
    def test_tier_1_within_2_days(self):
        tier, amount = _calculate_liability_tier(0)
        assert tier == "tier_1"
        assert amount == 50.00

    def test_tier_1_at_boundary(self):
        tier, amount = _calculate_liability_tier(2)
        assert tier == "tier_1"
        assert amount == 50.00

    def test_tier_2_at_3_days(self):
        tier, amount = _calculate_liability_tier(3)
        assert tier == "tier_2"
        assert amount == 500.00

    def test_tier_2_at_60_days(self):
        tier, amount = _calculate_liability_tier(60)
        assert tier == "tier_2"
        assert amount == 500.00

    def test_tier_3_beyond_60_days(self):
        tier, amount = _calculate_liability_tier(61)
        assert tier == "tier_3"
        assert amount == -1.0

    def test_tier_3_at_90_days(self):
        tier, amount = _calculate_liability_tier(90)
        assert tier == "tier_3"
        assert amount == -1.0


# ---------------------------------------------------------------------------
# EFT coverage check
# ---------------------------------------------------------------------------

class TestEftCoverage:
    def test_debit_card_covered(self):
        assert _is_eft_covered("debit_card") is True

    def test_ach_covered(self):
        assert _is_eft_covered("ach") is True

    def test_wire_covered(self):
        assert _is_eft_covered("wire") is True

    def test_p2p_covered(self):
        assert _is_eft_covered("p2p") is True

    def test_atm_covered(self):
        assert _is_eft_covered("atm") is True

    def test_credit_card_not_covered(self):
        assert _is_eft_covered("credit_card") is False

    def test_check_not_covered(self):
        assert _is_eft_covered("check") is False

    def test_case_insensitive(self):
        assert _is_eft_covered("DEBIT_CARD") is True
        assert _is_eft_covered("ACH") is True

    def test_debit_card_ending_covered(self):
        assert _is_eft_covered("debit_card_ending_5678") is True


# ---------------------------------------------------------------------------
# Reg E compliance checker
# ---------------------------------------------------------------------------

class TestRegECompliance:
    def setup_method(self):
        self.checker = ComplianceChecker()

    def test_no_violations_without_dispute_context(self):
        """No Reg E checks when no dispute data in session."""
        violations = self.checker.check_reg_e_compliance(
            "Here is your refund.",
            session_state={},
        )
        assert len(violations) == 0

    def test_internal_tier_exposure_detected(self):
        """Exposing internal 'tier 1' / 'tier 2' labels is a violation."""
        violations = self.checker.check_reg_e_compliance(
            "Your dispute falls under Tier 1 liability.",
            session_state={
                "dispute_data": {"amount": 350, "liability_tier": "tier_1", "max_liability": 50},
                "dispute_eligibility": {"liability_tier": "tier_1", "max_liability": 50},
            },
        )
        assert any(v.rule_id == "reg_e:internal_tier_exposed" for v in violations)

    def test_tier_2_exposure_detected(self):
        violations = self.checker.check_reg_e_compliance(
            "You are in liability tier 2, so your max liability is $500.",
            session_state={
                "dispute_data": {"amount": 1000, "liability_tier": "tier_2", "max_liability": 500},
                "dispute_eligibility": {"liability_tier": "tier_2", "max_liability": 500},
            },
        )
        assert any(v.rule_id == "reg_e:internal_tier_exposed" for v in violations)

    def test_no_tier_exposure_for_clean_response(self):
        violations = self.checker.check_reg_e_compliance(
            "Your maximum liability is limited to $50.",
            session_state={
                "dispute_data": {"amount": 350, "liability_tier": "tier_1", "max_liability": 50},
                "dispute_eligibility": {"liability_tier": "tier_1", "max_liability": 50},
            },
        )
        assert not any(v.rule_id == "reg_e:internal_tier_exposed" for v in violations)

    def test_provisional_credit_exceeds_dispute_amount(self):
        """Provisional credit cannot exceed the disputed amount."""
        violations = self.checker.check_reg_e_compliance(
            "We have issued a provisional credit of $500.00 to your account.",
            session_state={
                "dispute_data": {"amount": 350, "liability_tier": "tier_1", "max_liability": 50},
                "dispute_eligibility": {"liability_tier": "tier_1", "max_liability": 50},
            },
            current_step="assess_provisional_credit",
        )
        assert any(v.rule_id == "reg_e:provisional_credit_exceeds_dispute" for v in violations)

    def test_correct_provisional_credit_passes(self):
        """Correct provisional credit ($300 = $350 - $50) should pass."""
        violations = self.checker.check_reg_e_compliance(
            "We have issued a provisional credit of $300.00 to your account.",
            session_state={
                "dispute_data": {"amount": 350, "liability_tier": "tier_1", "max_liability": 50},
                "dispute_eligibility": {"liability_tier": "tier_1", "max_liability": 50},
            },
            current_step="assess_provisional_credit",
        )
        assert not any(v.rule_id == "reg_e:provisional_credit_exceeds_dispute" for v in violations)

    def test_provisional_credit_miscalculation_detected(self):
        """Verify SymPy catches wrong provisional credit math."""
        violations = self.checker.check_reg_e_compliance(
            "Your provisional credit has been applied.",
            session_state={
                "dispute_data": {"amount": 350, "liability_tier": "tier_1", "max_liability": 50},
                "dispute_eligibility": {"liability_tier": "tier_1", "max_liability": 50},
                "provisional_credit": {
                    "provisional_credit_issued": True,
                    "provisional_credit_amount": 250.00,  # Wrong: should be 300
                },
            },
        )
        assert any(v.rule_id == "reg_e:provisional_credit_miscalculated" for v in violations)

    def test_correct_provisional_credit_math_passes(self):
        violations = self.checker.check_reg_e_compliance(
            "Your provisional credit has been applied.",
            session_state={
                "dispute_data": {"amount": 350, "liability_tier": "tier_1", "max_liability": 50},
                "dispute_eligibility": {"liability_tier": "tier_1", "max_liability": 50},
                "provisional_credit": {
                    "provisional_credit_issued": True,
                    "provisional_credit_amount": 300.00,  # Correct: 350 - 50
                },
            },
        )
        assert not any(v.rule_id == "reg_e:provisional_credit_miscalculated" for v in violations)

    def test_wrong_timeline_units_detected(self):
        """45/90 are calendar days, not business days."""
        violations = self.checker.check_reg_e_compliance(
            "The investigation will be completed within 90 business days.",
            session_state={
                "dispute_data": {"amount": 350, "liability_tier": "tier_1", "max_liability": 50},
            },
            current_step="file_dispute",
        )
        assert any(v.rule_id == "reg_e:incorrect_timeline_units" for v in violations)

    def test_correct_timeline_passes(self):
        """'10 business days' is correct — should not trigger violation."""
        violations = self.checker.check_reg_e_compliance(
            "We will investigate within 10 business days.",
            session_state={
                "dispute_data": {"amount": 350, "liability_tier": "tier_1", "max_liability": 50},
            },
            current_step="file_dispute",
        )
        assert not any(v.rule_id == "reg_e:incorrect_timeline_units" for v in violations)


# ---------------------------------------------------------------------------
# Required disclosures for dispute steps
# ---------------------------------------------------------------------------

class TestDisputeDisclosures:
    def setup_method(self):
        self.checker = ComplianceChecker()

    def test_file_dispute_missing_disclosures(self):
        """file_dispute step requires 4 disclosures."""
        violations = self.checker.check_procedure_compliance(
            "Your dispute has been filed.",
            current_step="file_dispute",
        )
        # Should flag missing: investigation_timeline, provisional_credit_notice,
        # written_acknowledgment (reference number might match "dispute")
        assert len(violations) >= 2

    def test_file_dispute_all_disclosures_present(self):
        response = (
            "Your dispute reference number DISP-20260301120000 has been filed. "
            "We will investigate within 10 business days. If more time is needed, "
            "provisional credit will be applied to your account. "
            "Written acknowledgment will be sent within 1 business day."
        )
        violations = self.checker.check_procedure_compliance(
            response, current_step="file_dispute",
        )
        disclosure_violations = [v for v in violations if v.rule_id.startswith("disclosure:")]
        assert len(disclosure_violations) == 0

    def test_deny_late_dispute_missing_disclosures(self):
        violations = self.checker.check_procedure_compliance(
            "Unfortunately we cannot help.",
            current_step="deny_late_dispute",
        )
        assert any("timeframe_explanation" in v.rule_id for v in violations)
        assert any("alternative_options" in v.rule_id for v in violations)

    def test_deny_late_dispute_all_disclosures_present(self):
        response = (
            "Unfortunately, this dispute was reported outside the 60 day window "
            "required by federal regulation. As an alternative, I can escalate "
            "this to a supervisor for a courtesy review."
        )
        violations = self.checker.check_procedure_compliance(
            response, current_step="deny_late_dispute",
        )
        disclosure_violations = [v for v in violations if v.rule_id.startswith("disclosure:")]
        assert len(disclosure_violations) == 0

    def test_close_dispute_requires_summary(self):
        violations = self.checker.check_procedure_compliance(
            "Thanks for calling.",
            current_step="close_dispute",
        )
        assert len(violations) >= 1

    def test_close_dispute_with_summary_passes(self):
        response = (
            "To summarize: your dispute has been filed with reference DISP-001. "
            "The investigation results will be available within 10 business days. "
            "Please monitor your account for any additional unauthorized activity."
        )
        violations = self.checker.check_procedure_compliance(
            response, current_step="close_dispute",
        )
        disclosure_violations = [v for v in violations if v.rule_id.startswith("disclosure:")]
        assert len(disclosure_violations) == 0

    def test_assess_provisional_credit_disclosures(self):
        violations = self.checker.check_procedure_compliance(
            "Credit has been applied.",
            current_step="assess_provisional_credit",
        )
        # Should flag missing amount and condition disclosure
        assert len(violations) >= 1

    def test_assess_provisional_credit_complete(self):
        response = (
            "A provisional credit of $300.00 has been applied to your account. "
            "This credit will remain unless the investigation determines the "
            "transaction was authorized."
        )
        violations = self.checker.check_procedure_compliance(
            response, current_step="assess_provisional_credit",
        )
        disclosure_violations = [v for v in violations if v.rule_id.startswith("disclosure:")]
        assert len(disclosure_violations) == 0


# ---------------------------------------------------------------------------
# Integration: check_all with Reg E context
# ---------------------------------------------------------------------------

class TestRegECheckAllIntegration:
    def setup_method(self):
        self.checker = ComplianceChecker()

    def test_check_all_activates_reg_e_for_dispute_procedure(self):
        """check_all runs Reg E checks when procedure_id is cs_eft_dispute."""
        violations = self.checker.check_all(
            "Your dispute falls under Tier 1.",
            session_state={
                "dispute_data": {"amount": 350, "liability_tier": "tier_1", "max_liability": 50},
                "dispute_eligibility": {"liability_tier": "tier_1", "max_liability": 50},
            },
            procedure_id="cs_eft_dispute",
        )
        assert any(v.rule_id == "reg_e:internal_tier_exposed" for v in violations)

    def test_check_all_activates_reg_e_for_dispute_data(self):
        """check_all runs Reg E checks when dispute_data is in session state."""
        violations = self.checker.check_all(
            "Your dispute falls under Tier 2.",
            session_state={
                "dispute_data": {"amount": 1000, "liability_tier": "tier_2", "max_liability": 500},
            },
        )
        assert any(v.rule_id == "reg_e:internal_tier_exposed" for v in violations)

    def test_check_all_skips_reg_e_without_dispute_context(self):
        """check_all does not run Reg E checks for non-dispute sessions."""
        violations = self.checker.check_all(
            "Here is your refund of $79.99.",
            session_state={"order_total": 79.99},
            procedure_id="customer_service_refund",
        )
        assert not any(v.rule_id.startswith("reg_e:") for v in violations)

    def test_combined_financial_and_reg_e_violations(self):
        """Both financial and Reg E violations can be detected together."""
        violations = self.checker.check_all(
            "We will refund $999.99 to your account. Tier 1 applies.",
            session_state={
                "order_total": 100.00,
                "dispute_data": {"amount": 100, "liability_tier": "tier_1", "max_liability": 50},
                "dispute_eligibility": {"liability_tier": "tier_1", "max_liability": 50},
            },
            procedure_id="cs_eft_dispute",
        )
        has_financial = any(v.rule_id.startswith("financial:") for v in violations)
        has_reg_e = any(v.rule_id.startswith("reg_e:") for v in violations)
        assert has_financial
        assert has_reg_e
