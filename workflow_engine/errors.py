"""Structured error hierarchy for the workflow engine.

Provides typed exceptions with error codes for consistent error handling
across tools, agents, and API endpoints.
"""

from enum import Enum
from typing import Any, Optional


class ErrorCode(str, Enum):
    """Standardized error codes for API and internal use."""

    # General
    INTERNAL_ERROR = "INTERNAL_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    TIMEOUT = "TIMEOUT"

    # Auth
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    AUTHORIZATION_DENIED = "AUTHORIZATION_DENIED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    INVALID_TOKEN = "INVALID_TOKEN"

    # Rate limiting
    RATE_LIMITED = "RATE_LIMITED"

    # Business domain
    ORDER_NOT_FOUND = "ORDER_NOT_FOUND"
    CUSTOMER_NOT_FOUND = "CUSTOMER_NOT_FOUND"
    ALERT_NOT_FOUND = "ALERT_NOT_FOUND"
    REFUND_INELIGIBLE = "REFUND_INELIGIBLE"
    ACCOUNT_ALREADY_FLAGGED = "ACCOUNT_ALREADY_FLAGGED"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"

    # Procedure engine
    PROCEDURE_NOT_FOUND = "PROCEDURE_NOT_FOUND"
    INVALID_PROCEDURE = "INVALID_PROCEDURE"
    INVALID_STEP_TRANSITION = "INVALID_STEP_TRANSITION"
    PROCEDURE_ALREADY_ACTIVE = "PROCEDURE_ALREADY_ACTIVE"

    # Tool errors
    TOOL_EXECUTION_ERROR = "TOOL_EXECUTION_ERROR"
    TOOL_VALIDATION_ERROR = "TOOL_VALIDATION_ERROR"

    # External service
    EXTERNAL_SERVICE_ERROR = "EXTERNAL_SERVICE_ERROR"
    LLM_ERROR = "LLM_ERROR"


class WorkflowEngineError(Exception):
    """Base exception for all workflow engine errors."""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.INTERNAL_ERROR,
        status_code: int = 500,
        details: Optional[dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "error": {
                "code": self.code.value,
                "message": self.message,
            }
        }
        if self.details:
            result["error"]["details"] = self.details
        return result


# --- Specific error types ---


class NotFoundError(WorkflowEngineError):
    """Resource not found."""

    def __init__(self, resource: str, identifier: str, code: ErrorCode = ErrorCode.NOT_FOUND):
        super().__init__(
            message=f"{resource} '{identifier}' not found",
            code=code,
            status_code=404,
            details={"resource": resource, "identifier": identifier},
        )


class ValidationError(WorkflowEngineError):
    """Input validation failed."""

    def __init__(self, message: str, field: Optional[str] = None, details: Optional[dict] = None):
        d = details or {}
        if field:
            d["field"] = field
        super().__init__(
            message=message,
            code=ErrorCode.VALIDATION_ERROR,
            status_code=422,
            details=d,
        )


class AuthenticationError(WorkflowEngineError):
    """Authentication failed."""

    def __init__(self, message: str = "Authentication required", code: ErrorCode = ErrorCode.AUTHENTICATION_REQUIRED):
        super().__init__(message=message, code=code, status_code=401)


class AuthorizationError(WorkflowEngineError):
    """Authorization denied."""

    def __init__(self, message: str = "Insufficient permissions", required_permission: Optional[str] = None):
        details = {}
        if required_permission:
            details["required_permission"] = required_permission
        super().__init__(
            message=message,
            code=ErrorCode.AUTHORIZATION_DENIED,
            status_code=403,
            details=details,
        )


class RateLimitError(WorkflowEngineError):
    """Rate limit exceeded."""

    def __init__(self, retry_after: int = 60):
        super().__init__(
            message="Rate limit exceeded",
            code=ErrorCode.RATE_LIMITED,
            status_code=429,
            details={"retry_after_seconds": retry_after},
        )


class ToolExecutionError(WorkflowEngineError):
    """Tool execution failed."""

    def __init__(self, tool_name: str, message: str, details: Optional[dict] = None):
        d = {"tool": tool_name}
        if details:
            d.update(details)
        super().__init__(
            message=f"Tool '{tool_name}' failed: {message}",
            code=ErrorCode.TOOL_EXECUTION_ERROR,
            status_code=500,
            details=d,
        )


class ExternalServiceError(WorkflowEngineError):
    """External service call failed."""

    def __init__(self, service: str, message: str):
        super().__init__(
            message=f"External service '{service}' error: {message}",
            code=ErrorCode.EXTERNAL_SERVICE_ERROR,
            status_code=502,
            details={"service": service},
        )


class ProcedureError(WorkflowEngineError):
    """Procedure engine error."""

    def __init__(self, message: str, code: ErrorCode = ErrorCode.INVALID_PROCEDURE, details: Optional[dict] = None):
        super().__init__(message=message, code=code, status_code=400, details=details)
