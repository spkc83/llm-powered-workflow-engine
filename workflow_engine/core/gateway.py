"""Independently enforced action dispatch and reconciliation boundary."""

from typing import Any, Protocol

from pydantic import BaseModel

from workflow_engine.core.kernel import ActionRecord, ActionStatus, CaseKernel
from workflow_engine.core.policy import PolicyRegistry


class ConnectorOutcome(BaseModel):
    status: ActionStatus
    details: dict[str, Any]

    @classmethod
    def succeeded(cls, details: dict[str, Any]) -> "ConnectorOutcome":
        return cls(status=ActionStatus.SUCCEEDED, details=details)

    @classmethod
    def failed(cls, details: dict[str, Any]) -> "ConnectorOutcome":
        return cls(status=ActionStatus.FAILED, details=details)

    @classmethod
    def unknown(cls, details: dict[str, Any]) -> "ConnectorOutcome":
        return cls(status=ActionStatus.UNKNOWN, details=details)


class ActionConnector(Protocol):
    async def dispatch(self, command) -> ConnectorOutcome: ...
    async def reconcile(self, command, prior: dict[str, Any] | None) -> ConnectorOutcome: ...


class ActionGateway:
    def __init__(
        self,
        kernel: CaseKernel,
        connectors: dict[str, ActionConnector],
        policy_registry: PolicyRegistry | None = None,
    ):
        self.kernel = kernel
        self.connectors = connectors
        self.policy_registry = policy_registry

    async def dispatch(self, action: ActionRecord) -> ActionRecord:
        if action.status is not ActionStatus.AUTHORIZED:
            return action
        if self.policy_registry is not None:
            self.policy_registry.require_active(action.command.policy_package_id)
        connector = self.connectors.get(action.command.action)
        if connector is None:
            raise ValueError(f"Unknown action connector: {action.command.action}")
        claimed_action, claimed = await self.kernel.store.claim_action(action.action_id)
        if not claimed:
            return claimed_action
        try:
            outcome = await connector.dispatch(action.command)
        except Exception as exc:
            outcome = ConnectorOutcome.unknown(
                {"reason": "connector_exception", "error_type": type(exc).__name__}
            )
        return await self.kernel.record_outcome(action.action_id, outcome.status, outcome.details)

    async def reconcile(self, action: ActionRecord) -> ActionRecord:
        if action.status is not ActionStatus.UNKNOWN:
            return action
        connector = self.connectors[action.command.action]
        outcome = await connector.reconcile(action.command, action.outcome)
        if outcome.status is ActionStatus.SUCCEEDED:
            return await self.kernel.record_outcome(
                action.action_id, ActionStatus.RECONCILED, outcome.details
            )
        return await self.kernel.record_outcome(action.action_id, outcome.status, outcome.details)
