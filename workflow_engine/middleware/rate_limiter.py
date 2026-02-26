"""Simple in-memory rate limiter middleware.

Uses a sliding window counter per user/IP. For production, replace with
Redis-backed rate limiting (e.g., via fastapi-limiter).
"""

import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

from ..errors import RateLimitError
from ..logging_config import get_logger
from ..settings import get_settings

logger = get_logger("middleware.rate_limiter")


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """In-memory sliding window rate limiter."""

    def __init__(self, app):
        super().__init__(app)
        # key -> list of timestamps
        self._requests: dict[str, list[float]] = defaultdict(list)

    def _get_key(self, request: Request) -> str:
        """Get rate limit key from user or IP."""
        user = getattr(request.state, "user", None)
        if user:
            return f"user:{user.user_id}"
        client_ip = request.client.host if request.client else "unknown"
        return f"ip:{client_ip}"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        settings = get_settings()

        if not settings.rate_limit_enabled:
            return await call_next(request)

        # Skip rate limiting for health checks
        if request.url.path == "/health":
            return await call_next(request)

        key = self._get_key(request)
        now = time.time()
        window = settings.rate_limit_window_seconds
        max_requests = settings.rate_limit_requests

        # Clean expired entries
        self._requests[key] = [
            ts for ts in self._requests[key] if now - ts < window
        ]

        if len(self._requests[key]) >= max_requests:
            logger.warning("Rate limit exceeded for %s", key)
            err = RateLimitError(retry_after=window)
            return JSONResponse(
                status_code=err.status_code,
                content=err.to_dict(),
                headers={"Retry-After": str(window)},
            )

        self._requests[key].append(now)
        return await call_next(request)
