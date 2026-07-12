"""Separation between authenticated actors and serviced customers."""

from pydantic import BaseModel

from workflow_engine.auth.models import Permission, Role, UserContext
from workflow_engine.errors import AuthorizationError


class CustomerContext(BaseModel):
    actor_id: str
    customer_id: str
    delegated: bool


def resolve_customer_context(actor: UserContext, customer_id: str) -> CustomerContext:
    """Authorize a self-service or delegated staff customer context."""
    if actor.role is Role.CUSTOMER:
        if actor.user_id != customer_id:
            raise AuthorizationError("Customer identity does not match authenticated subject")
        return CustomerContext(actor_id=actor.user_id, customer_id=customer_id, delegated=False)

    if not actor.has_permission(Permission.CUSTOMER_READ):
        raise AuthorizationError(
            "Customer delegation requires customer read permission",
            required_permission=Permission.CUSTOMER_READ.value,
        )
    return CustomerContext(actor_id=actor.user_id, customer_id=customer_id, delegated=True)


def session_owner_id(actor_id: str, customer_id: str) -> str:
    """Create an ADK session owner key that cannot cross actor/customer pairs."""
    return f"actor:{actor_id}:customer:{customer_id}"
