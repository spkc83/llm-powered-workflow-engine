"""Tests for agent guardrails — output filtering, tool arg validation, and integrated reasoning pipeline."""

import pytest
from datetime import datetime, timedelta, timezone

from workflow_engine.agents.guardrails import (
    check_response,
    filter_response,
    steer_response,
    validate_tool_args,
)


class TestResponseGuardrails:
    def test_clean_response_passes(self):
        violations = check_response("Your refund of $79.99 has been processed.")
        assert len(violations) == 0

    def test_detects_internal_step_id(self):
        violations = check_response("Moving to step_id: check_eligibility")
        assert any(v.rule == "internal_step_id" for v in violations)

    def test_detects_db_reference(self):
        violations = check_response("The sql query returned no results")
        assert any(v.rule == "internal_db_reference" for v in violations)

    def test_detects_credential_mention(self):
        violations = check_response("The api_key is stored in the environment")
        assert any(v.rule == "sensitive_credential" for v in violations)

    def test_detects_unauthorized_promise(self):
        violations = check_response("I guarantee you will get a full refund")
        assert any(v.rule == "unauthorized_promise" for v in violations)


class TestResponseFiltering:
    def test_redacts_internal_data(self):
        filtered, violations = filter_response("step_id: greet_and_collect is active")
        assert "step_id" not in filtered.lower() or "REDACTED" in filtered
        assert len(violations) > 0

    def test_clean_text_unchanged(self):
        text = "Your order has been refunded."
        filtered, violations = filter_response(text)
        assert filtered == text
        assert len(violations) == 0


class TestToolArgValidation:
    def test_valid_args_pass(self):
        violations = validate_tool_args("lookup_order", {"order_id": "ORD-123"})
        assert len(violations) == 0

    def test_negative_amount_blocked(self):
        violations = validate_tool_args("issue_refund", {"amount": -50.0})
        assert any(v.rule == "negative_amount" for v in violations)
        assert any(v.severity == "block" for v in violations)

    def test_invalid_order_id_format(self):
        violations = validate_tool_args("lookup_order", {"order_id": "INVALID"})
        assert any(v.rule == "invalid_order_id_format" for v in violations)

    def test_valid_order_id_passes(self):
        violations = validate_tool_args("lookup_order", {"order_id": "ORD-456"})
        id_violations = [v for v in violations if v.rule == "invalid_order_id_format"]
        assert len(id_violations) == 0

    def test_input_too_long_blocked(self):
        violations = validate_tool_args("add_case_note", {"note": "x" * 3000})
        assert any(v.rule == "input_too_long" for v in violations)

    def test_normal_length_passes(self):
        violations = validate_tool_args("add_case_note", {"note": "Customer confirmed."})
        assert len(violations) == 0


# ===========================================================================
# Integration: steer_response pipeline (pattern + reasoning + compliance)
# ===========================================================================


class TestSteerResponseIntegration:
    """Integration tests for the full guardrail pipeline."""

    @pytest.mark.asyncio
    async def test_clean_response_no_procedure(self):
        """Clean response without procedure context passes through."""
        text = "Your order has been refunded. Thank you!"
        result, violations, verification = await steer_response(
            text=text,
            session_state={},
        )
        assert result == text
        assert len(violations) == 0

    @pytest.mark.asyncio
    async def test_pattern_rails_run_first(self):
        """Pattern-based redaction runs even with reasoning enabled."""
        text = "The step_id: greet_and_collect is the first step in the procedure_id: cs_refund."
        result, violations, verification = await steer_response(
            text=text,
            session_state={},
        )
        assert "REDACTED" in result
        assert any(v.rule == "internal_step_id" for v in violations)

    @pytest.mark.asyncio
    async def test_reasoning_catches_wrong_amount(self):
        """Reasoning rails catch amount exceeding order total."""
        order_date = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")
        session_state = {
            "order_total": 50.00,
            "order_date": order_date,
            "order_status": "delivered",
            "is_refundable_category": True,
        }
        procedure_def = {
            "id": "cs_refund",
            "name": "Refund",
            "steps": [
                {
                    "id": "check_eligibility",
                    "instruction": "Check eligibility.",
                    "action": "evaluate",
                    "conditions": [
                        {"if": "order_date within 30 days AND order_status in [delivered, shipped] AND category not in non_refundable_list", "next_step": "process_refund"},
                        {"if": "order_date outside 30 days", "next_step": "deny_refund_window"},
                    ],
                },
                {
                    "id": "process_refund",
                    "instruction": "Process refund.",
                    "action": "tool_call",
                    "tool": "issue_refund",
                    "on_success": "end",
                    "on_failure": "end",
                },
                {
                    "id": "deny_refund_window",
                    "instruction": "Deny.",
                    "action": "inform",
                    "next_step": "end",
                },
            ],
        }

        text = "Your refund of $100.00 has been approved!"
        result, violations, verification = await steer_response(
            text=text,
            session_state=session_state,
            procedure_id="cs_refund",
            current_step="process_refund",
            procedure_def=procedure_def,
        )
        # Verification should detect the amount violation
        assert verification is not None
        assert verification.verdict == "INVALID"

    @pytest.mark.asyncio
    async def test_combined_pattern_and_reasoning(self):
        """Both pattern and reasoning violations are detected together."""
        order_date = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")
        session_state = {
            "order_total": 50.00,
            "order_date": order_date,
            "order_status": "delivered",
            "is_refundable_category": True,
        }
        procedure_def = {
            "id": "cs_refund",
            "name": "Refund",
            "steps": [
                {
                    "id": "process_refund",
                    "instruction": "Process refund.",
                    "action": "tool_call",
                    "tool": "issue_refund",
                    "on_success": "end",
                    "on_failure": "end",
                },
            ],
        }

        # Text with both internal data AND wrong amount
        text = "The step_id: process_refund confirms your refund of $999.99."
        result, violations, verification = await steer_response(
            text=text,
            session_state=session_state,
            procedure_id="cs_refund",
            current_step="process_refund",
            procedure_def=procedure_def,
        )
        # Pattern violations should have redacted internal data
        assert any(v.rule == "internal_step_id" for v in violations)
        # Reasoning should catch the amount
        assert verification is not None

    @pytest.mark.asyncio
    async def test_backward_compatible_filter_response(self):
        """Existing filter_response function still works unchanged."""
        text = "Your refund is confirmed."
        filtered, violations = filter_response(text)
        assert filtered == text
        assert len(violations) == 0

    @pytest.mark.asyncio
    async def test_backward_compatible_check_response(self):
        """Existing check_response function still works unchanged."""
        violations = check_response("I guarantee you will get your money back.")
        assert any(v.rule == "unauthorized_promise" for v in violations)
