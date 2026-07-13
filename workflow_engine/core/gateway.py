"""Independently enforced action dispatch and reconciliation boundary."""

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

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


@dataclass(frozen=True)
class ResolvedActionConnector:
    action_name: str
    binding_id: str
    binding_version: str
    contract_version: str
    connector: ActionConnector


class ActionConnectorResolver(Protocol):
    def resolve(
        self,
        action_name: str,
        *,
        binding_id: str | None = None,
        binding_version: str | None = None,
        contract_version: str | None = None,
    ) -> ResolvedActionConnector: ...


class PolicyResolver(Protocol):
    async def require_active(self, package_id: str): ...
    async def require_authorization_snapshot(
        self, package_id: str, activation_signature: str
    ): ...


class ActionGateway:
    def __init__(
        self,
        kernel: CaseKernel,
        connectors: Mapping[str, ActionConnector] | ActionConnectorResolver,
        policy_registry: PolicyRegistry | None = None,
        policy_resolver: PolicyResolver | None = None,
    ):
        self.kernel = kernel
        self.connectors = connectors
        self.policy_registry = policy_registry
        self.policy_resolver = policy_resolver

    def _resolve_connector(self, command, *, use_pinned_binding: bool = True) -> ResolvedActionConnector:
        resolver = getattr(self.connectors, "resolve", None)
        if callable(resolver):
            return resolver(
                command.action,
                binding_id=(getattr(command, "connector_binding_id", None) if use_pinned_binding else None),
                binding_version=(
                    getattr(command, "connector_binding_version", None)
                    if use_pinned_binding
                    else None
                ),
                contract_version=(
                    getattr(command, "contract_version", None) if use_pinned_binding else None
                ),
            )
        connector = self.connectors.get(command.action)  # type: ignore[union-attr]
        if connector is None:
            raise ValueError(f"Unknown action connector: {command.action}")
        return ResolvedActionConnector(
            action_name=command.action,
            binding_id="legacy",
            binding_version="1",
            contract_version="1",
            connector=connector,
        )

    async def authorize(
        self, command, expected_version: int
    ) -> ActionRecord:
        # Initial authorization always selects the server's active binding. Any
        # binding fields present in an inbound command are ignored and replaced.
        resolved = self._resolve_connector(command, use_pinned_binding=False)
        update = {}
        if "connector_binding_id" in command.__class__.model_fields:
            update = {
                "connector_binding_id": resolved.binding_id,
                "connector_binding_version": resolved.binding_version,
                "contract_version": resolved.contract_version,
            }
            command = command.model_copy(update=update)
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
        connector = self._resolve_connector(action.command).connector
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
        connector = self._resolve_connector(action.command).connector
        outcome = await connector.reconcile(action.command, action.outcome)
        if outcome.status is ActionStatus.SUCCEEDED:
            return await self.kernel.record_outcome(
                action.action_id, ActionStatus.RECONCILED, outcome.details
            )
        return await self.kernel.record_outcome(action.action_id, outcome.status, outcome.details)
