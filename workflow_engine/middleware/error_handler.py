"""Global error handling middleware for FastAPI.

Catches all WorkflowEngineError subclasses and converts them to
consistent JSON error responses.
"""

from fastapi import Request
from fastapi.responses import JSONResponse

from ..errors import WorkflowEngineError, ErrorCode
from ..logging_config import get_logger

logger = get_logger("middleware.error")


async def workflow_error_handler(request: Request, exc: WorkflowEngineError) -> JSONResponse:
    """Handle WorkflowEngineError exceptions with structured JSON responses."""
    logger.warning(
        "Request error: %s (code=%s, status=%d)",
        exc.message,
        exc.code.value,
        exc.status_code,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict(),
    )


async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions with a generic 500 response."""
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    error = WorkflowEngineError(
        message="An internal error occurred",
        code=ErrorCode.INTERNAL_ERROR,
        status_code=500,
    )
    return JSONResponse(
        status_code=500,
        content=error.to_dict(),
    )
