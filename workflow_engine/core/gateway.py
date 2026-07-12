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


class PolicyResolver(Protocol):
    async def require_active(self, package_id: str): ...
    async def require_authorization_snapshot(
        self, package_id: str, activation_signature: str
    ): ...


class ActionGateway:
    def __init__(
        self,
        kernel: CaseKernel,
        connectors: dict[str, ActionConnector],
        policy_registry: PolicyRegistry | None = None,
        policy_resolver: PolicyResolver | None = None,
    ):
        self.kernel = kernel
        self.connectors = connectors
        self.policy_registry = policy_registry
        self.policy_resolver = policy_resolver

    async def authorize(
        self, command, expected_version: int
    ) -> ActionRecord:
        if self.policy_registry is None and self.policy_resolver is None:
            return await self.kernel.authorize_action(command, expected_version)
        if self.policy_resolver is not None:
            package = await self.policy_resolver.require_active(command.policy_package_id)
        else:
            assert self.policy_registry is not None
            package = self.policy_registry.require_active(command.policy_package_id)
        case = await self.kernel.store.get_case(command.case_id)
        if case is None:
            raise ValueError(f"Action case does not exist: {command.case_id}")
        if package.procedure_id != case.procedure_id:
            raise ValueError(
                "Policy package procedure does not match the action case procedure"
            )
        allowed = package.rules.get("allowed_actions")
        if allowed is not None and command.action not in allowed:
            raise ValueError(
                f"Policy package {package.package_id} does not allow {command.action}"
            )
        stamped = command.model_copy(
            update={"policy_activation_signature": package.activation_signature}
        )
        return await self.kernel.authorize_action(stamped, expected_version)

    async def dispatch(self, action: ActionRecord) -> ActionRecord:
        if action.status is not ActionStatus.AUTHORIZED:
            return action
        if self.policy_registry is not None or self.policy_resolver is not None:
            if action.command.policy_activation_signature:
                if self.policy_resolver is not None:
                    package = await self.policy_resolver.require_authorization_snapshot(
                        action.command.policy_package_id,
                        action.command.policy_activation_signature,
                    )
                else:
                    assert self.policy_registry is not None
                    package = self.policy_registry.require_authorization_snapshot(
                        action.command.policy_package_id,
                        action.command.policy_activation_signature,
                    )
            else:
                # Backward compatibility for v2 action records; new actions are
                # stamped by authorize() and remain valid after policy retirement.
                if self.policy_resolver is not None:
                    package = await self.policy_resolver.require_active(
                        action.command.policy_package_id
                    )
                else:
                    assert self.policy_registry is not None
                    package = self.policy_registry.require_active(
                        action.command.policy_package_id
                    )
            allowed = package.rules.get("allowed_actions")
            if allowed is not None and action.command.action not in allowed:
                raise ValueError(
                    f"Policy package {package.package_id} does not allow {action.command.action}"
                )
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
        if action.status is ActionStatus.DISPATCHED:
            action = await self.kernel.record_outcome(
                action.action_id,
                ActionStatus.UNKNOWN,
                {
                    "reason": "dispatch_lease_expired_before_outcome_recorded",
                    "prior": action.outcome,
                },
            )
        if action.status is not ActionStatus.UNKNOWN:
            return action
        connector = self.connectors[action.command.action]
        outcome = await connector.reconcile(action.command, action.outcome)
        if outcome.status is ActionStatus.SUCCEEDED:
            return await self.kernel.record_outcome(
                action.action_id, ActionStatus.RECONCILED, outcome.details
            )
        return await self.kernel.record_outcome(action.action_id, outcome.status, outcome.details)
