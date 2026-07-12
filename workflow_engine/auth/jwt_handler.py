"""JWT token creation and verification."""

from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt

from .models import Role, UserContext
from .rbac import get_permissions_for_role
from ..errors import AuthenticationError, ErrorCode
from ..settings import get_settings


def create_access_token(
    user_id: str,
    role: Role,
    extra_permissions: Optional[list[str]] = None,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a signed JWT access token.

    Args:
        user_id: The user identifier.
        role: The user's role.
        extra_permissions: Additional permissions beyond role defaults.
        expires_delta: Custom expiration time.

    Returns:
        Encoded JWT string.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=settings.auth_token_expire_minutes))

    payload = {
        "sub": user_id,
        "role": role.value,
        "iat": now,
        "exp": expire,
        "iss": settings.auth_issuer,
    }
    if extra_permissions:
        payload["permissions"] = extra_permissions

    return jwt.encode(payload, settings.auth_secret_key, algorithm=settings.auth_algorithm)


def decode_access_token(token: str) -> UserContext:
    """Decode and validate a JWT access token.

    Args:
        token: The encoded JWT string.

    Returns:
        UserContext with the user's identity and permissions.

    Raises:
        AuthenticationError: If the token is invalid or expired.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.auth_secret_key,
            algorithms=[settings.auth_algorithm],
            issuer=settings.auth_issuer,
        )
    except jwt.ExpiredSignatureError:
        raise AuthenticationError("Token has expired", code=ErrorCode.TOKEN_EXPIRED)
    except jwt.InvalidTokenError as e:
        raise AuthenticationError(f"Invalid token: {e}", code=ErrorCode.INVALID_TOKEN)

    role = Role(payload["role"])
    permissions = get_permissions_for_role(role)

    # Add any explicit permission overrides from the token
    if "permissions" in payload:
        permissions.update(payload["permissions"])

    return UserContext(
        user_id=payload["sub"],
        role=role,
        permissions=permissions,
        token_issued_at=datetime.fromtimestamp(payload["iat"], tz=timezone.utc),
    )
