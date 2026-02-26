"""Authentication middleware for FastAPI.

Extracts and validates JWT tokens from the Authorization header.
When auth is disabled (dev mode), creates a default admin context.
"""

from typing import Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from ..auth.jwt_handler import decode_access_token
from ..auth.models import Role, UserContext
from ..auth.rbac import build_user_context
from ..errors import AuthenticationError
from ..logging_config import get_logger, user_id_var
from ..settings import get_settings

logger = get_logger("middleware.auth")

# Paths that never require authentication
PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}


class AuthMiddleware(BaseHTTPMiddleware):
    """JWT authentication middleware.

    When auth_enabled=True: validates Bearer token from Authorization header.
    When auth_enabled=False: injects a default admin context for development.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        settings = get_settings()

        # Skip auth for public paths
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        if not settings.auth_enabled:
            # Dev mode: create default admin context
            user = build_user_context(
                user_id=request.query_params.get("user_id", "dev-user"),
                role=Role.ADMIN,
            )
            request.state.user = user
            user_id_var.set(user.user_id)
            return await call_next(request)

        # Production mode: validate JWT
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise AuthenticationError("Missing or invalid Authorization header")

        token = auth_header[7:]  # Strip "Bearer "
        user = decode_access_token(token)
        request.state.user = user
        user_id_var.set(user.user_id)
        logger.info("Authenticated user: %s (role=%s)", user.user_id, user.role.value)

        return await call_next(request)


def get_current_user(request: Request) -> UserContext:
    """Extract the authenticated user from the request state.

    Use as a FastAPI dependency:
        @app.get("/api/v1/orders")
        async def list_orders(user: UserContext = Depends(get_current_user)):
            ...
    """
    user: Optional[UserContext] = getattr(request.state, "user", None)
    if user is None:
        raise AuthenticationError("No authenticated user")
    return user
