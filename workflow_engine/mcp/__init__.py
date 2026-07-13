"""Optional model-safe MCP facade over the trusted action bridge."""

from .server import TrustedContextResolver, create_action_mcp_server

__all__ = ["TrustedContextResolver", "create_action_mcp_server"]
