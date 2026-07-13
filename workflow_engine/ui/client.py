"""Typed HTTP client used by the Shiny development/operator console."""

from __future__ import annotations

import os
from typing import Any

import httpx


class WorkflowApiClient:
    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        resolved_url = base_url or os.getenv("BACKEND_URL") or "http://localhost:8000"
        self.base_url = resolved_url.rstrip("/")
        self.token = token if token is not None else os.getenv("BACKEND_AUTH_TOKEN")
        self.timeout = timeout

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = {**self.headers, **kwargs.pop("headers", {})}
        async with httpx.AsyncClient(timeout=self.timeout, headers=headers) as client:
            response = await client.request(method, f"{self.base_url}{path}", **kwargs)
            response.raise_for_status()
            return response.json()

    async def customers(self) -> dict[str, Any]:
        return await self.request("GET", "/api/v1/customers")

    async def chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", "/api/v1/chat", json=payload)

    async def actions_catalog(self) -> dict[str, Any]:
        """Return the closed catalog of actions available to the conversation UI."""
        return await self.request("GET", "/api/v1/actions/catalog")

    async def propose_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a typed action proposal without performing the action."""
        return await self.request("POST", "/api/v1/action-proposals", json=payload)

    async def action_proposals(
        self, conversation_id: str | None = None
    ) -> dict[str, Any]:
        """List proposals, optionally scoped to the active conversation."""
        params = {"conversation_id": conversation_id} if conversation_id else None
        return await self.request("GET", "/api/v1/action-proposals", params=params)

    async def action_proposal(self, proposal_id: str) -> dict[str, Any]:
        """Get one proposal and its current confirmation state."""
        return await self.request("GET", f"/api/v1/action-proposals/{proposal_id}")

    async def confirm_action_proposal(self, proposal_id: str) -> dict[str, Any]:
        """Confirm a pending proposal through the trusted host API."""
        return await self.request(
            "POST", f"/api/v1/action-proposals/{proposal_id}/confirm"
        )

    async def cancel_action_proposal(self, proposal_id: str) -> dict[str, Any]:
        """Cancel a pending proposal through the trusted host API."""
        return await self.request(
            "POST", f"/api/v1/action-proposals/{proposal_id}/cancel"
        )

    async def action_status(self, action_id: str) -> dict[str, Any]:
        """Get authoritative action status, outcome, and event history."""
        return await self.request("GET", f"/api/v1/actions/{action_id}")

    async def session_state(self, session_id: str, user_id: str) -> dict[str, Any]:
        return await self.request(
            "GET", f"/api/v1/session/{session_id}/state", params={"user_id": user_id}
        )

    async def sessions(self, user_id: str) -> dict[str, Any]:
        return await self.request("GET", "/api/v1/sessions", params={"user_id": user_id})

    async def procedures(self) -> dict[str, Any]:
        return await self.request("GET", "/api/v1/procedures")

    async def table(self, table_name: str) -> dict[str, Any]:
        return await self.request("GET", f"/api/v1/tables/{table_name}")

    async def health(self) -> dict[str, Any]:
        return await self.request("GET", "/health")

    async def metrics(self) -> dict[str, Any]:
        return await self.request("GET", "/api/v1/metrics")

    async def audit_integrity(self) -> dict[str, Any]:
        return await self.request("GET", "/api/v1/operations/audit-integrity")
