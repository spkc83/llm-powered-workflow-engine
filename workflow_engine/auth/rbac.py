"""Role-based access control (RBAC) configuration and helpers."""

from functools import wraps
from typing import Callable

from .models import Permission, Role, UserContext
from ..errors import AuthorizationError

# --- Role-to-Permission mapping ---

ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.ADMIN: set(Permission),  # All permissions

    Role.SUPERVISOR: {
        # Customer service (full)
        Permission.ORDER_READ, Permission.ORDER_WRITE,
        Permission.REFUND_READ, Permission.REFUND_WRITE,
        Permission.CUSTOMER_READ, Permission.CUSTOMER_WRITE,
        Permission.CASE_READ, Permission.CASE_WRITE,
        Permission.ESCALATION_CREATE,
        # Fraud (full)
        Permission.FRAUD_ALERT_READ, Permission.FRAUD_ALERT_WRITE,
        Permission.ACCOUNT_FLAG, Permission.SAR_SUBMIT,
        Permission.TRANSACTION_READ, Permission.DEVICE_READ,
        # Read-only admin
        Permission.ADMIN_READ, Permission.TABLE_BROWSE,
        Permission.SESSION_READ, Permission.PROCEDURE_READ,
    },

    Role.CUSTOMER_SERVICE_REP: {
        Permission.ORDER_READ,
        Permission.REFUND_READ, Permission.REFUND_WRITE,
        Permission.CUSTOMER_READ,
        Permission.CASE_READ, Permission.CASE_WRITE,
        Permission.ESCALATION_CREATE,
        Permission.SESSION_READ, Permission.PROCEDURE_READ,
    },

    Role.FRAUD_ANALYST: {
        Permission.FRAUD_ALERT_READ, Permission.FRAUD_ALERT_WRITE,
        Permission.ACCOUNT_FLAG, Permission.SAR_SUBMIT,
        Permission.TRANSACTION_READ, Permission.DEVICE_READ,
        Permission.CASE_READ, Permission.CASE_WRITE,
        Permission.ESCALATION_CREATE,
        Permission.SESSION_READ, Permission.PROCEDURE_READ,
    },

    Role.READONLY: {
        Permission.ORDER_READ,
        Permission.CUSTOMER_READ,
        Permission.CASE_READ,
        Permission.REFUND_READ,
        Permission.FRAUD_ALERT_READ,
        Permission.TRANSACTION_READ,
        Permission.SESSION_READ, Permission.PROCEDURE_READ,
    },

    # Self-service customers are authorized by resource ownership rather than
    # broad staff permissions.
    Role.CUSTOMER: set(),

    Role.INTEGRATION: {
        Permission.CUSTOMER_READ,
        Permission.CASE_READ,
        Permission.CHANNEL_INGEST,
        Permission.CHANNEL_DELIVERY,
        Permission.PROVIDER_CALLBACK,
    },
}


def get_permissions_for_role(role: Role) -> set[str]:
    """Get all permission strings for a given role."""
    perms = ROLE_PERMISSIONS.get(role, set())
    return {p.value for p in perms}


def build_user_context(user_id: str, role: Role, extra_permissions: list[str] | None = None) -> UserContext:
    """Build a UserContext with role-derived permissions plus any overrides."""
    permissions = get_permissions_for_role(role)
    if extra_permissions:
        permissions.update(extra_permissions)
    return UserContext(user_id=user_id, role=role, permissions=permissions)


def require_permission(permission: Permission):
    """Decorator that checks the user context for a required permission.

    Usage:
        @require_permission(Permission.REFUND_WRITE)
        async def issue_refund(request, user: UserContext):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            user: UserContext | None = kwargs.get("user")
            if user is None:
                raise AuthorizationError("No user context available")
            if not user.has_permission(permission):
                raise AuthorizationError(
                    f"Permission '{permission.value}' required",
                    required_permission=permission.value,
                )
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def require_role(*roles: Role):
    """Decorator that checks the user context for an allowed role."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            user: UserContext | None = kwargs.get("user")
            if user is None:
                raise AuthorizationError("No user context available")
            if user.role not in roles:
                role_names = ", ".join(r.value for r in roles)
                raise AuthorizationError(f"One of roles [{role_names}] required")
            return await func(*args, **kwargs)
        return wrapper
    return decorator
