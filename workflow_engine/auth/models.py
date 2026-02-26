"""Authentication and authorization data models."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Role(str, Enum):
    """User roles for RBAC."""
    ADMIN = "admin"
    SUPERVISOR = "supervisor"
    CUSTOMER_SERVICE_REP = "customer_service_rep"
    FRAUD_ANALYST = "fraud_analyst"
    READONLY = "readonly"


class Permission(str, Enum):
    """Fine-grained permissions for tool and endpoint access."""
    # Customer service
    ORDER_READ = "order:read"
    ORDER_WRITE = "order:write"
    REFUND_READ = "refund:read"
    REFUND_WRITE = "refund:write"
    CUSTOMER_READ = "customer:read"
    CUSTOMER_WRITE = "customer:write"
    CASE_READ = "case:read"
    CASE_WRITE = "case:write"
    ESCALATION_CREATE = "escalation:create"

    # Fraud operations
    FRAUD_ALERT_READ = "fraud_alert:read"
    FRAUD_ALERT_WRITE = "fraud_alert:write"
    ACCOUNT_FLAG = "account:flag"
    SAR_SUBMIT = "sar:submit"
    TRANSACTION_READ = "transaction:read"
    DEVICE_READ = "device:read"

    # Admin
    ADMIN_READ = "admin:read"
    ADMIN_WRITE = "admin:write"
    TABLE_BROWSE = "table:browse"
    SESSION_READ = "session:read"
    PROCEDURE_READ = "procedure:read"


class TokenPayload(BaseModel):
    """JWT token payload."""
    sub: str = Field(description="Subject (user ID)")
    role: Role = Field(description="User role")
    exp: datetime = Field(description="Expiration time")
    iat: datetime = Field(description="Issued at")
    iss: str = Field(default="workflow-engine", description="Issuer")
    permissions: list[str] = Field(default_factory=list, description="Explicit permission overrides")


class UserContext(BaseModel):
    """Authenticated user context attached to requests."""
    user_id: str
    role: Role
    permissions: set[str] = Field(default_factory=set)
    token_issued_at: Optional[datetime] = None

    def has_permission(self, permission: Permission) -> bool:
        """Check if user has a specific permission."""
        return permission.value in self.permissions

    def has_any_permission(self, *permissions: Permission) -> bool:
        """Check if user has any of the specified permissions."""
        return any(p.value in self.permissions for p in permissions)
