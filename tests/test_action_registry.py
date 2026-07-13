import hashlib
import json

import httpx
import pytest
import yaml
from pydantic import ValidationError

from workflow_engine.core.gateway import ActionGateway, ConnectorOutcome
from workflow_engine.core.kernel import ActionCommand, ActionStatus, CaseKernel, SQLiteCoreStore
from workflow_engine.integrations.registry import (
    ActionConnectorRegistry,
    ActionRegistryConfig,
    RestActionBinding,
    RestActionConnector,
    SQLiteActionBinding,
    WebSocketActionBinding,
    load_registry_config,
)
from workflow_engine.integrations.sandbox import SQLiteSandboxActionConnector
from workflow_engine.settings import Environment


def _command() -> ActionCommand:
    return ActionCommand(
        action="issue_store_credit",
        case_id="CASE-1",
        policy_package_id="refund@1:NAM",
        actor_id="rep-1",
        idempotency_key="credit:ORD-1",
        parameters={"order_id": "ORD-1", "amount": 20.0},
        parameter_fact_refs={},
        required_fact_authority={},
        consent_evidence_ref="message:1",
    )


def _openapi(tmp_path):
    content = yaml.safe_dump(
        {
            "openapi": "3.1.0",
            "info": {"title": "Actions", "version": "1"},
            "paths": {
                "/credits": {"post": {"operationId": "issueStoreCredit", "responses": {}}},
                "/credits/status": {
                    "get": {"operationId": "getStoreCredit", "responses": {}}
                },
            },
        },
        sort_keys=True,
    ).encode()
    path = tmp_path / "provider-openapi.yaml"
    path.write_bytes(content)
    return path, hashlib.sha256(content).hexdigest()


def _rest_binding(tmp_path, **overrides):
    path, digest = _openapi(tmp_path)
    data = {
        "action_name": "issue_store_credit",
        "binding_id": "commerce-credit",
        "binding_version": "2026-07-13",
        "contract_version": "1",
        "transport": "rest",
        "base_url": "https://commerce.example.test",
        "allowed_hosts": ["commerce.example.test"],
        "openapi": {"path": path, "sha256": digest},
        "execute": {
            "operation_id": "issueStoreCredit",
            "method": "POST",
            "path": "/credits",
            "body": {
                "orderId": "$.parameters.order_id",
                "amount": "$.parameters.amount",
            },
        },
        "reconcile": {
            "operation_id": "getStoreCredit",
            "method": "GET",
            "path": "/credits/status",
            "query": {"idempotencyKey": "$.idempotency_key"},
        },
        "response_fields": {"credit_id": "$.credit.id"},
    }
    data.update(overrides)
    return RestActionBinding.model_validate(data)


def test_registry_rejects_unknown_actions_and_inline_secrets(tmp_path):
    with pytest.raises(ValidationError, match="Unknown action"):
        SQLiteActionBinding(
            action_name="model_invented_action",
            binding_id="bad",
            binding_version="1",
            contract_version="1",
        )
    with pytest.raises(ValidationError, match="inline secrets"):
        _rest_binding(tmp_path, secret_ref="literal-password")


def test_registry_rejects_unsafe_hosts_and_async_without_reconciliation(tmp_path):
    with pytest.raises(ValidationError, match="outside allowed_hosts"):
        _rest_binding(tmp_path, allowed_hosts=["different.example.test"])
    with pytest.raises(ValidationError, match="reconciliation"):
        _rest_binding(tmp_path, reconcile=None)


def test_registry_rejects_demo_and_insecure_transport_in_production(tmp_path):
    class Connector:
        async def dispatch(self, command):
            return ConnectorOutcome.succeeded({})

        async def reconcile(self, command, prior):
            return ConnectorOutcome.succeeded({})

    sqlite = SQLiteActionBinding(
        action_name="issue_store_credit",
        binding_id="demo",
        binding_version="1",
        contract_version="1",
    )
    with pytest.raises(ValueError, match="forbidden in production"):
        ActionConnectorRegistry(
            ActionRegistryConfig(bindings=[sqlite]),
            environment=Environment.PRODUCTION,
            sqlite_connectors={"demo": Connector()},
        )

    binding = _rest_binding(tmp_path, base_url="http://commerce.example.test")
    with pytest.raises(ValueError, match="require HTTPS"):
        ActionConnectorRegistry(
            ActionRegistryConfig(bindings=[binding]),
            environment=Environment.PRODUCTION,
        )


def test_pinned_openapi_must_match_operation_and_digest(tmp_path):
    binding = _rest_binding(tmp_path)
    bad = binding.model_copy(
        update={"execute": binding.execute.model_copy(update={"operation_id": "missing"})}
    )
    with pytest.raises(ValueError, match="does not match pinned OpenAPI"):
        ActionConnectorRegistry(ActionRegistryConfig(bindings=[bad]))

    binding.openapi.path.write_text("openapi: 3.1.0\npaths: {}\n")
    with pytest.raises(ValueError, match="digest mismatch"):
        ActionConnectorRegistry(ActionRegistryConfig(bindings=[binding]))


@pytest.mark.asyncio
async def test_rest_connector_sends_idempotency_and_persists_only_allowlisted_response(tmp_path):
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            201,
            json={
                "provider_operation_id": "OP-1",
                "credit": {"id": "CR-1"},
                "sensitive": "must-not-be-persisted",
            },
        )

    transport = httpx.MockTransport(handler)
    connector = RestActionConnector(
        _rest_binding(tmp_path),
        client_factory=lambda **kwargs: httpx.AsyncClient(transport=transport, **kwargs),
    )
    outcome = await connector.dispatch(_command())

    assert outcome.status is ActionStatus.SUCCEEDED
    assert requests[0].headers["Idempotency-Key"] == "credit:ORD-1"
    assert json.loads(requests[0].content) == {"orderId": "ORD-1", "amount": 20.0}
    assert outcome.details["provider_operation_id"] == "OP-1"
    assert outcome.details["result"] == {"credit_id": "CR-1"}
    assert "sensitive" not in str(outcome.details)


@pytest.mark.asyncio
async def test_rest_timeout_is_unknown_and_reconciliation_is_a_query(tmp_path):
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "POST":
            raise httpx.ReadTimeout("provider may have committed", request=request)
        return httpx.Response(
            200,
            json={"provider_operation_id": "OP-2", "credit": {"id": "CR-2"}},
        )

    transport = httpx.MockTransport(handler)
    connector = RestActionConnector(
        _rest_binding(tmp_path),
        client_factory=lambda **kwargs: httpx.AsyncClient(transport=transport, **kwargs),
    )
    ambiguous = await connector.dispatch(_command())
    reconciled = await connector.reconcile(_command(), ambiguous.details)

    assert ambiguous.status is ActionStatus.UNKNOWN
    assert ambiguous.details["reason"] == "provider_outcome_ambiguous"
    assert reconciled.status is ActionStatus.SUCCEEDED
    assert calls == ["POST", "GET"]


def test_registry_resolves_only_active_or_exact_immutable_binding(tmp_path):
    registry = ActionConnectorRegistry(
        ActionRegistryConfig(bindings=[_rest_binding(tmp_path)])
    )
    current = registry.resolve("issue_store_credit")
    exact = registry.resolve(
        "issue_store_credit",
        binding_id="commerce-credit",
        binding_version="2026-07-13",
        contract_version="1",
    )
    assert current is exact
    with pytest.raises(ValueError, match="unavailable"):
        registry.resolve(
            "issue_store_credit",
            binding_id="commerce-credit",
            binding_version="old",
            contract_version="1",
        )


@pytest.mark.asyncio
async def test_gateway_stamps_server_resolved_binding_identity(tmp_path):
    class Connector:
        async def dispatch(self, command):
            return ConnectorOutcome.succeeded({})

        async def reconcile(self, command, prior):
            return ConnectorOutcome.succeeded({})

    binding = SQLiteActionBinding(
        action_name="update_case_status",
        binding_id="case-system",
        binding_version="7",
        contract_version="3",
    )
    registry = ActionConnectorRegistry(
        ActionRegistryConfig(bindings=[binding]),
        sqlite_connectors={"case-system": Connector()},
    )
    store = SQLiteCoreStore(tmp_path / "core.db")
    await store.initialize()
    kernel = CaseKernel(store)
    case = await kernel.create_case("CASE-PIN", "CUST-1", "cs_complaint", "1")
    command = ActionCommand(
        action="update_case_status",
        case_id=case.case_id,
        policy_package_id="case@1:NAM",
        actor_id="rep-1",
        idempotency_key="case:pin:1",
        parameters={"target_status": "closed", "reason": "resolved"},
        parameter_fact_refs={},
        required_fact_authority={},
    )

    action = await ActionGateway(kernel, registry).authorize(command, case.version)
    assert action.command.connector_binding_id == "case-system"
    assert action.command.connector_binding_version == "7"
    assert action.command.contract_version == "3"


def test_websocket_contract_is_validated_but_not_silently_executed():
    binding = WebSocketActionBinding(
        action_name="issue_store_credit",
        binding_id="ws-credit",
        binding_version="1",
        contract_version="1",
        url="wss://actions.example.test/ws",
        allowed_hosts=["actions.example.test"],
        execute={"message_type": "command"},
        reconcile={"message_type": "query"},
        acknowledgement_type="ack",
        outcome_type="outcome",
    )
    with pytest.raises(ValueError, match="contract-only"):
        ActionConnectorRegistry(ActionRegistryConfig(bindings=[binding]))


def test_registry_config_resolves_relative_openapi_path(tmp_path):
    openapi_path, digest = _openapi(tmp_path)
    binding = _rest_binding(tmp_path).model_dump(mode="json")
    binding["openapi"] = {"path": openapi_path.name, "sha256": digest}
    config_path = tmp_path / "actions.yaml"
    config_path.write_text(yaml.safe_dump({"version": 1, "bindings": [binding]}))

    config = load_registry_config(config_path)
    assert config.bindings[0].openapi.path == openapi_path


def test_partial_registry_capabilities_do_not_advertise_unbound_actions(tmp_path):
    connector = SQLiteSandboxActionConnector(tmp_path / "partial.db")
    registry = ActionConnectorRegistry(
        ActionRegistryConfig(
            bindings=[
                SQLiteActionBinding(
                    action_name="issue_store_credit",
                    binding_id="credit-only",
                    binding_version="1",
                    contract_version="1",
                )
            ]
        ),
        sqlite_connectors={"credit-only": connector},
    )

    assert registry.capabilities() == [
        {
            "action_name": "issue_store_credit",
            "binding_id": "credit-only",
            "binding_version": "1",
            "contract_version": "1",
        }
    ]
    with pytest.raises(ValueError, match="No enabled action binding"):
        registry.resolve("issue_refund")
