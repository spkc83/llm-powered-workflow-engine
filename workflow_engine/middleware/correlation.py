"""Request correlation ID middleware.

Assigns a unique correlation ID to each request for distributed tracing
and log correlation. The ID is propagated via context variables and
returned in response headers.
"""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from ..logging_config import (
    correlation_id_var,
    generate_correlation_id,
    session_id_var,
)


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Attach a correlation ID to every request."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Use incoming header if present, else generate
        correlation_id = request.headers.get("X-Correlation-ID") or generate_correlation_id()
        correlation_id_var.set(correlation_id)

        # Also set session_id if present in query or body
        session_id = request.query_params.get("session_id")
        if session_id:
            session_id_var.set(session_id)

        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response
