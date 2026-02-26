"""Tests for the structured error hierarchy."""

from workflow_engine.errors import (
    AuthenticationError,
    AuthorizationError,
    ErrorCode,
    NotFoundError,
    ProcedureError,
    RateLimitError,
    ToolExecutionError,
    ValidationError,
    WorkflowEngineError,
)


class TestWorkflowEngineError:
    def test_base_error(self):
        e = WorkflowEngineError("test error")
        assert e.message == "test error"
        assert e.code == ErrorCode.INTERNAL_ERROR
        assert e.status_code == 500

    def test_to_dict(self):
        e = WorkflowEngineError("fail", code=ErrorCode.TIMEOUT, details={"timeout": 30})
        d = e.to_dict()
        assert d["error"]["code"] == "TIMEOUT"
        assert d["error"]["message"] == "fail"
        assert d["error"]["details"]["timeout"] == 30


class TestNotFoundError:
    def test_fields(self):
        e = NotFoundError("Order", "ORD-123")
        assert e.status_code == 404
        assert "ORD-123" in e.message
        assert e.details["resource"] == "Order"

    def test_custom_code(self):
        e = NotFoundError("Order", "ORD-123", code=ErrorCode.ORDER_NOT_FOUND)
        assert e.code == ErrorCode.ORDER_NOT_FOUND


class TestValidationError:
    def test_with_field(self):
        e = ValidationError("bad input", field="amount")
        assert e.status_code == 422
        assert e.details["field"] == "amount"


class TestAuthErrors:
    def test_authentication(self):
        e = AuthenticationError()
        assert e.status_code == 401

    def test_authorization(self):
        e = AuthorizationError("no access", required_permission="refund:write")
        assert e.status_code == 403
        assert e.details["required_permission"] == "refund:write"


class TestRateLimitError:
    def test_default_retry(self):
        e = RateLimitError()
        assert e.status_code == 429
        assert e.details["retry_after_seconds"] == 60


class TestToolExecutionError:
    def test_includes_tool_name(self):
        e = ToolExecutionError("issue_refund", "DB connection failed")
        assert "issue_refund" in e.message
        assert e.details["tool"] == "issue_refund"


class TestProcedureError:
    def test_default_code(self):
        e = ProcedureError("step missing")
        assert e.code == ErrorCode.INVALID_PROCEDURE
        assert e.status_code == 400
