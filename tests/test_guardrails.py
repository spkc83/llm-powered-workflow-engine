"""Tests for agent guardrails — output filtering and tool arg validation."""

from workflow_engine.agents.guardrails import (
    check_response,
    filter_response,
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
