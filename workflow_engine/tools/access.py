"""Runtime authorization checks for model-invoked tools."""

from google.adk.tools import ToolContext

from workflow_engine.errors import AuthorizationError
from workflow_engine.tools.catalog import TOOL_CATALOG


def authorize_tool(
    tool_name: str,
    tool_context: ToolContext,
    *,
    customer_id: str | None = None,
) -> None:
    control = TOOL_CATALOG[tool_name]
    required = control.required_permission
    permissions = set(tool_context.state.get("actor_permissions", []))
    self_service = (
        control.self_service_allowed
        and tool_context.state.get("actor_role") == "customer"
        and bool(tool_context.state.get("customer_id"))
    )
    if required is not None and required.value not in permissions and not self_service:
        raise AuthorizationError(
            f"Tool '{tool_name}' is not authorized for this actor",
            required_permission=required.value,
        )

    bound_customer = tool_context.state.get("customer_id")
    if customer_id is not None and bound_customer != customer_id:
        raise AuthorizationError("Tool customer does not match the authenticated session customer")
