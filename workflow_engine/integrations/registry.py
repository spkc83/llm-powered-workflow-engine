"""Startup-validated bindings from the closed action catalog to provider services.

OpenAPI describes the provider's wire shape.  It never defines action permission,
policy, consent, approval, or fact-authority semantics; those remain owned by the
typed core action catalog.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Callable, Literal, Mapping, Protocol
from urllib.parse import urljoin, urlparse

import httpx
import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from workflow_engine.core.action_specs import ACTION_SPECIFICATIONS
from workflow_engine.core.adapter_loading import load_factory
from workflow_engine.core.gateway import (
    ActionConnector,
    ConnectorOutcome,
    ResolvedActionConnector,
)
from workflow_engine.core.kernel import ActionCommand
from workflow_engine.settings import Environment


class ActionTransport(str, Enum):
    SQLITE = "sqlite"
    REST = "rest"
    PYTHON = "python"
    WEBSOCKET = "websocket"


class OpenApiDocument(BaseModel):
    """Pinned local OpenAPI document used to validate configured operations."""

    path: Path
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")


class HttpOperation(BaseModel):
    operation_id: str = Field(min_length=1)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "POST"
    path: str
    body: dict[str, str] = Field(default_factory=dict)
    query: dict[str, str] = Field(default_factory=dict)

    @field_validator("path")
    @classmethod
    def require_relative_path(cls, value: str) -> str:
        if not value.startswith("/") or urlparse(value).scheme or "//" in value:
            raise ValueError("Operation path must be an absolute-path reference")
        return value


class HttpStatusMapping(BaseModel):
    succeeded: set[int] = Field(default_factory=lambda: {200, 201})
    accepted: set[int] = Field(default_factory=lambda: {202})
    failed: set[int] = Field(default_factory=lambda: {400, 401, 403, 404, 409, 422})

    @model_validator(mode="after")
    def disjoint(self) -> "HttpStatusMapping":
        groups = [self.succeeded, self.accepted, self.failed]
        if any(groups[index] & other for index, group in enumerate(groups) for other in groups[index + 1 :]):
            raise ValueError("HTTP status outcome mappings must be disjoint")
        return self


class BindingBase(BaseModel):
    action_name: str
    binding_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.:-]+$")
    binding_version: str = Field(min_length=1)
    contract_version: str = Field(min_length=1)
    enabled: bool = True

    @field_validator("action_name")
    @classmethod
    def closed_catalog_only(cls, value: str) -> str:
        if value not in ACTION_SPECIFICATIONS:
            raise ValueError(f"Unknown action name: {value}")
        return value


class SQLiteActionBinding(BindingBase):
    transport: Literal[ActionTransport.SQLITE] = ActionTransport.SQLITE
    database_url: str = "sqlite+aiosqlite:///data/upstream_sandbox.db"

    @field_validator("database_url")
    @classmethod
    def sqlite_url_only(cls, value: str) -> str:
        if not value.startswith("sqlite"):
            raise ValueError("SQLite action bindings require a SQLite database URL")
        return value


class RestActionBinding(BindingBase):
    transport: Literal[ActionTransport.REST] = ActionTransport.REST
    base_url: str
    allowed_hosts: set[str] = Field(min_length=1)
    timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    idempotency_header: str = "Idempotency-Key"
    secret_ref: str | None = None
    auth_header: str = "Authorization"
    auth_scheme: str = "Bearer"
    openapi: OpenApiDocument
    execute: HttpOperation
    reconcile: HttpOperation | None = None
    statuses: HttpStatusMapping = Field(default_factory=HttpStatusMapping)
    provider_operation_id_pointer: str | None = "provider_operation_id"
    response_fields: dict[str, str] = Field(
        default_factory=dict,
        description="Allowlisted provider response fields persisted in action outcomes",
    )

    @model_validator(mode="after")
    def validate_rest_contract(self) -> "RestActionBinding":
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("REST base_url must be an HTTP(S) origin")
        if parsed.hostname not in self.allowed_hosts:
            raise ValueError("REST base_url host is outside allowed_hosts")
        if self.secret_ref and not self.secret_ref.startswith(("env://", "secret://")):
            raise ValueError("Credentials must use env:// or secret:// references; inline secrets are forbidden")
        if self.statuses.accepted and self.reconcile is None:
            raise ValueError("Asynchronous HTTP status mappings require a reconciliation operation")
        return self


class PythonActionBinding(BindingBase):
    transport: Literal[ActionTransport.PYTHON] = ActionTransport.PYTHON
    factory: str = Field(pattern=r"^[A-Za-z_][\w.]*:[A-Za-z_][\w.]*$")


class WebSocketMessageBinding(BaseModel):
    message_type: str = Field(min_length=1)
    payload: dict[str, str] = Field(default_factory=dict)


class WebSocketActionBinding(BindingBase):
    """Declarative WS contract; runtime execution is intentionally not built in."""

    transport: Literal[ActionTransport.WEBSOCKET] = ActionTransport.WEBSOCKET
    url: str
    allowed_hosts: set[str] = Field(min_length=1)
    subprotocol: str | None = None
    secret_ref: str | None = None
    execute: WebSocketMessageBinding
    reconcile: WebSocketMessageBinding
    acknowledgement_type: str = Field(min_length=1)
    outcome_type: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_ws_contract(self) -> "WebSocketActionBinding":
        parsed = urlparse(self.url)
        if parsed.scheme not in {"ws", "wss"} or not parsed.hostname:
            raise ValueError("WebSocket URL must use ws:// or wss://")
        if parsed.hostname not in self.allowed_hosts:
            raise ValueError("WebSocket host is outside allowed_hosts")
        if self.secret_ref and not self.secret_ref.startswith(("env://", "secret://")):
            raise ValueError("Credentials must use env:// or secret:// references; inline secrets are forbidden")
        return self


ActionConnectorBinding = Annotated[
    SQLiteActionBinding
    | RestActionBinding
    | PythonActionBinding
    | WebSocketActionBinding,
    Field(discriminator="transport"),
]


class ActionRegistryConfig(BaseModel):
    version: int = Field(default=1, ge=1)
    bindings: list[ActionConnectorBinding]

    @model_validator(mode="after")
    def unique_active_actions(self) -> "ActionRegistryConfig":
        active = [binding.action_name for binding in self.bindings if binding.enabled]
        if len(active) != len(set(active)):
            raise ValueError("Only one enabled binding is allowed per action")
        identities = [(binding.binding_id, binding.binding_version) for binding in self.bindings]
        if len(identities) != len(set(identities)):
            raise ValueError("Binding ID/version pairs must be unique")
        return self


class SecretProvider(Protocol):
    def resolve(self, reference: str) -> str: ...


class EnvironmentSecretProvider:
    def resolve(self, reference: str) -> str:
        import os

        if not reference.startswith("env://"):
            raise ValueError("The built-in secret provider supports only env:// references")
        name = reference.removeprefix("env://")
        value = os.getenv(name)
        if not value:
            raise ValueError(f"Required secret environment variable is not set: {name}")
        return value


def _source(command: ActionCommand, expression: str, prior: Mapping[str, Any] | None = None) -> Any:
    """Resolve a deliberately small, non-evaluating mapping language."""

    roots: dict[str, Any] = {
        "action": command.action,
        "case_id": command.case_id,
        "actor_id": command.actor_id,
        "idempotency_key": command.idempotency_key,
        "parameters": command.parameters,
        "prior": dict(prior or {}),
    }
    parts = expression.removeprefix("$.").split(".")
    value: Any = roots
    for part in parts:
        if not isinstance(value, Mapping) or part not in value:
            raise ValueError(f"Configured mapping source does not exist: {expression}")
        value = value[part]
    return value


def _pointer(document: Mapping[str, Any], pointer: str | None) -> Any:
    if not pointer:
        return None
    value: Any = document
    for part in pointer.removeprefix("$.").split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


class RestActionConnector:
    """Generic REST command connector with explicit ambiguous-outcome semantics."""

    def __init__(
        self,
        binding: RestActionBinding,
        *,
        secret_provider: SecretProvider | None = None,
        client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
    ) -> None:
        self.binding = binding
        self.secret_provider = secret_provider or EnvironmentSecretProvider()
        self.client_factory = client_factory

    def _request(
        self,
        operation: HttpOperation,
        command: ActionCommand,
        prior: Mapping[str, Any] | None = None,
    ) -> tuple[str, dict[str, str], dict[str, Any], dict[str, Any]]:
        headers = {self.binding.idempotency_header: command.idempotency_key}
        if self.binding.secret_ref:
            secret = self.secret_provider.resolve(self.binding.secret_ref)
            headers[self.binding.auth_header] = f"{self.binding.auth_scheme} {secret}".strip()
        body = {target: _source(command, source, prior) for target, source in operation.body.items()}
        query = {target: _source(command, source, prior) for target, source in operation.query.items()}
        return urljoin(self.binding.base_url.rstrip("/") + "/", operation.path.lstrip("/")), headers, body, query

    async def _execute(
        self,
        operation: HttpOperation,
        command: ActionCommand,
        prior: Mapping[str, Any] | None = None,
    ) -> ConnectorOutcome:
        url, headers, body, query = self._request(operation, command, prior)
        try:
            async with self.client_factory(
                timeout=self.binding.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.request(
                    operation.method,
                    url,
                    headers=headers,
                    params=query,
                    json=body if operation.method != "GET" else None,
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            return ConnectorOutcome.unknown(
                {"reason": "provider_outcome_ambiguous", "error_type": type(exc).__name__}
            )

        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError):
            payload = {}
        details: dict[str, Any] = {
            "http_status": response.status_code,
            "provider_operation_id": _pointer(payload, self.binding.provider_operation_id_pointer),
            "result": {
                name: _pointer(payload, pointer)
                for name, pointer in self.binding.response_fields.items()
            },
        }
        if response.status_code in self.binding.statuses.succeeded:
            return ConnectorOutcome.succeeded(details)
        if response.status_code in self.binding.statuses.failed:
            return ConnectorOutcome.failed(details)
        return ConnectorOutcome.unknown({**details, "reason": "provider_not_terminal"})

    async def dispatch(self, command: ActionCommand) -> ConnectorOutcome:
        return await self._execute(self.binding.execute, command)

    async def reconcile(
        self, command: ActionCommand, prior: dict[str, Any] | None
    ) -> ConnectorOutcome:
        if self.binding.reconcile is None:
            return ConnectorOutcome.unknown(prior or {"reason": "reconciliation_not_configured"})
        return await self._execute(self.binding.reconcile, command, prior)


def _load_document(path: Path) -> dict[str, Any]:
    content = path.read_bytes()
    if path.suffix.lower() == ".json":
        value = json.loads(content)
    else:
        value = yaml.safe_load(content)
    if not isinstance(value, dict):
        raise ValueError(f"Configuration document must contain an object: {path}")
    return value


def _validate_openapi(binding: RestActionBinding) -> None:
    content = binding.openapi.path.read_bytes()
    actual = hashlib.sha256(content).hexdigest()
    if actual.lower() != binding.openapi.sha256.lower():
        raise ValueError(f"OpenAPI digest mismatch for binding {binding.binding_id}")
    document = _load_document(binding.openapi.path)
    operations: dict[str, tuple[str, str]] = {}
    for path, path_item in document.get("paths", {}).items():
        if not isinstance(path_item, Mapping):
            continue
        for method, operation in path_item.items():
            if isinstance(operation, Mapping) and operation.get("operationId"):
                operations[str(operation["operationId"])] = (str(method).upper(), str(path))
    for operation in (binding.execute, binding.reconcile):
        if operation is None:
            continue
        if operations.get(operation.operation_id) != (operation.method, operation.path):
            raise ValueError(
                f"Configured operation {operation.operation_id} does not match pinned OpenAPI"
            )


class ActionConnectorRegistry:
    """Immutable, startup-validated action binding and connector resolver."""

    def __init__(
        self,
        config: ActionRegistryConfig,
        *,
        environment: Environment = Environment.DEV,
        sqlite_connectors: Mapping[str, ActionConnector] | None = None,
        secret_provider: SecretProvider | None = None,
    ) -> None:
        self.config = config
        self.environment = environment
        self.sqlite_connectors = dict(sqlite_connectors or {})
        self.secret_provider = secret_provider
        self._resolved: dict[tuple[str, str, str], ResolvedActionConnector] = {}
        self._active: dict[str, ResolvedActionConnector] = {}
        self._build()

    def _build(self) -> None:
        for binding in self.config.bindings:
            if self.environment is Environment.PRODUCTION:
                if isinstance(binding, SQLiteActionBinding):
                    raise ValueError("SQLite/demo action bindings are forbidden in production")
                if isinstance(binding, RestActionBinding) and not binding.base_url.startswith("https://"):
                    raise ValueError("Production REST action bindings require HTTPS")
                if isinstance(binding, WebSocketActionBinding) and not binding.url.startswith("wss://"):
                    raise ValueError("Production WebSocket action bindings require WSS")
            connector: ActionConnector
            if isinstance(binding, RestActionBinding):
                _validate_openapi(binding)
                connector = RestActionConnector(binding, secret_provider=self.secret_provider)
            elif isinstance(binding, PythonActionBinding):
                candidate = load_factory(binding.factory)(binding)
                if not callable(getattr(candidate, "dispatch", None)) or not callable(
                    getattr(candidate, "reconcile", None)
                ):
                    raise TypeError("Python action connector must implement dispatch and reconcile")
                connector = candidate
            elif isinstance(binding, SQLiteActionBinding):
                sqlite_connector = self.sqlite_connectors.get(
                    binding.binding_id
                ) or self.sqlite_connectors.get(
                    binding.action_name
                )
                if sqlite_connector is None:
                    raise ValueError(f"No SQLite connector supplied for binding {binding.binding_id}")
                connector = sqlite_connector
            else:
                raise ValueError(
                    "WebSocket action bindings are contract-only; install a Python connector runtime"
                )
            resolved = ResolvedActionConnector(
                action_name=binding.action_name,
                binding_id=binding.binding_id,
                binding_version=binding.binding_version,
                contract_version=binding.contract_version,
                connector=connector,
            )
            key = (binding.action_name, binding.binding_id, binding.binding_version)
            self._resolved[key] = resolved
            if binding.enabled:
                self._active[binding.action_name] = resolved

    def resolve(
        self,
        action_name: str,
        *,
        binding_id: str | None = None,
        binding_version: str | None = None,
        contract_version: str | None = None,
    ) -> ResolvedActionConnector:
        if action_name not in ACTION_SPECIFICATIONS:
            raise ValueError(f"Unknown action connector: {action_name}")
        if binding_id is None and binding_version is None and contract_version is None:
            try:
                return self._active[action_name]
            except KeyError as exc:
                raise ValueError(f"No enabled action binding: {action_name}") from exc
        if not binding_id or not binding_version or not contract_version:
            raise ValueError("Binding ID, binding version, and contract version must be supplied together")
        try:
            resolved = self._resolved[(action_name, binding_id, binding_version)]
        except KeyError as exc:
            raise ValueError(
                f"Configured action binding is unavailable: {action_name}/{binding_id}/{binding_version}"
            ) from exc
        if resolved.contract_version != contract_version:
            raise ValueError(
                f"Configured action contract is unavailable: {action_name}/{contract_version}"
            )
        return resolved

    def capabilities(self) -> list[dict[str, str]]:
        return [
            {
                "action_name": item.action_name,
                "binding_id": item.binding_id,
                "binding_version": item.binding_version,
                "contract_version": item.contract_version,
            }
            for item in sorted(self._active.values(), key=lambda item: item.action_name)
        ]


def load_registry_config(path: Path) -> ActionRegistryConfig:
    document = _load_document(path)
    for binding in document.get("bindings", []):
        if not isinstance(binding, dict):
            continue
        openapi = binding.get("openapi")
        if isinstance(openapi, dict) and openapi.get("path"):
            openapi_path = Path(str(openapi["path"]))
            if not openapi_path.is_absolute():
                openapi["path"] = str(path.parent / openapi_path)
    return ActionRegistryConfig.model_validate(document)
