import asyncio

import pytest

from workflow_engine.core.gateway import ActionGateway, ConnectorOutcome
from workflow_engine.core.kernel import (
    ActionCommand,
    ActionStatus,
    CaseKernel,
    FactAuthority,
    FactProposal,
    OutboxStatus,
    SQLiteCoreStore,
    HandoffConflict,
)
from workflow_engine.core.workers import ActionDeliveryWorker, ReconciliationWorker
from workflow_engine.core.action_specs import ACTION_SPECIFICATIONS
from workflow_engine.core.action_service import ACTION_PERMISSIONS
from workflow_engine.tools.catalog import TOOL_CATALOG
from workflow_engine.core.policy import PolicyLifecycle, PolicyPackage, PolicyRegistry, PolicySigner
from workflow_engine.core.policy_store import PolicyService, SQLitePolicyRepository
from workflow_engine.core.action_service import ConsequentialActionRequest, ConsequentialActionService
from workflow_engine.integrations.contracts import SttRequest, TtsRequest
from workflow_engine.integrations.sandbox import (
    SandboxScenario,
    SQLiteHandoffQueueAdapter,
    SQLiteSandboxActionConnector,
    StubSpeechToTextAdapter,
    StubTextToSpeechAdapter,
)
from workflow_engine.integrations.contracts import HandoffRequest
from workflow_engine.integrations.loading import ProviderBundle, validate_provider_bundle
from workflow_engine.settings import Environment, Settings, UpstreamMode
from workflow_engine.conversation.runtime import ChannelKind, ConversationRuntime, MessageEnvelope
from workflow_engine.conversation.service import ConversationService, GeneratedTurn
from workflow_engine.conversation.contracts import RiskLevel
from workflow_engine.core.jurisdiction import JurisdictionGuard, JurisdictionProfile
from workflow_engine.core.adapter_loading import load_factory


def _command(key: str = "store-credit:ORD-1") -> ActionCommand:
    return ActionCommand(
        action="issue_store_credit",
        case_id="CASE-1",
        policy_package_id="store-credit@1:NAM",
        actor_id="rep-1",
        idempotency_key=key,
        parameters={"order_id": "ORD-1", "amount": 20.0},
        parameter_fact_refs={},
        required_fact_authority={},
        consent_evidence_ref="message:consent-1",
    )


def test_upstream_mode_defaults_sandbox_only_in_development():
    assert Settings(environment=Environment.DEV).effective_upstream_mode is UpstreamMode.SANDBOX
    assert Settings(environment=Environment.STAGING).effective_upstream_mode is UpstreamMode.DISABLED
    with pytest.raises(ValueError, match="forbidden"):
        Settings(
            environment=Environment.PRODUCTION,
            policy_signing_key="production-policy-key",
            upstream_mode=UpstreamMode.SANDBOX,
        )


@pytest.mark.asyncio
async def test_sandbox_action_timeout_after_commit_reconciles_without_duplication(tmp_path):
    connector = SQLiteSandboxActionConnector(tmp_path / "upstream.db")
    command = _command()
    await connector.set_scenario(command.idempotency_key, SandboxScenario.TIMEOUT_AFTER_COMMIT)

    ambiguous = await connector.dispatch(command)
    reconciled = await connector.reconcile(command, ambiguous.details)
    replay = await connector.dispatch(command)

    assert ambiguous.status is ActionStatus.UNKNOWN
    assert reconciled.status is ActionStatus.SUCCEEDED
    assert replay.status is ActionStatus.SUCCEEDED
    assert replay.details["idempotent_replay"] is True
    assert reconciled.details["provider_action_id"] == replay.details["provider_action_id"]


@pytest.mark.asyncio
async def test_sandbox_authoritative_resources_reject_obvious_secrets(tmp_path):
    connector = SQLiteSandboxActionConnector(tmp_path / "sensitive.db")
    with pytest.raises(ValueError, match="sensitive fields"):
        await connector.put_resource(
            "customer",
            "CUST-1",
            {"customer_id": "CUST-1", "payment": {"card_number": "4111"}},
        )


@pytest.mark.asyncio
async def test_speech_stubs_are_explicitly_simulated_and_redact_secret_dtmf():
    stt = await StubSpeechToTextAdapter().transcribe(
        SttRequest(
            event_id="EV-1",
            call_id="CALL-1",
            transcript_hint="4111111111111111",
            contains_secret_dtmf=True,
        )
    )
    tts = await StubTextToSpeechAdapter().synthesize(
        TtsRequest(request_id="REQ-1", call_id="CALL-1", text="Please confirm")
    )

    assert stt.simulated is True
    assert stt.redacted is True
    assert "4111" not in stt.transcript
    assert tts.simulated is True
    assert tts.media_ref.startswith("sandbox://")


@pytest.mark.asyncio
async def test_sandbox_handoff_queue_does_not_equate_queued_with_connected(tmp_path):
    adapter = SQLiteHandoffQueueAdapter(tmp_path / "queue.db")
    queued = await adapter.enqueue(
        HandoffRequest(
            handoff_id="HO-1",
            conversation_id="CONV-1",
            case_id="CASE-1",
            queue="customer-service",
            context={"summary": "customer requested a person"},
        )
    )
    connected = await adapter.set_status(queued.provider_ticket_id, "connected")

    assert queued.status == "queued"
    assert connected.status == "connected"


@pytest.mark.asyncio
async def test_only_one_human_agent_can_accept_a_handoff(tmp_path):
    store = SQLiteCoreStore(tmp_path / "handoff-cas.db")
    await store.initialize()
    kernel = CaseKernel(store)
    await kernel.create_case("CASE-HO", "CUST-1", "cs_complaint", "1")
    runtime = ConversationRuntime(store)
    handoff = await runtime.request_handoff("CONV-HO", "CASE-HO", {"summary": "help"})
    results = await asyncio.gather(
        runtime.accept_handoff(handoff.handoff_id, "agent-1"),
        runtime.accept_handoff(handoff.handoff_id, "agent-2"),
        return_exceptions=True,
    )
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, HandoffConflict) for result in results) == 1


@pytest.mark.asyncio
async def test_action_authorization_and_outbox_are_atomic_and_worker_is_restart_safe(tmp_path):
    class Connector:
        calls = 0

        async def dispatch(self, command):
            self.calls += 1
            return ConnectorOutcome.succeeded({"provider_ref": "P-1"})

        async def reconcile(self, command, prior):
            return ConnectorOutcome.succeeded(prior or {})

    store = SQLiteCoreStore(tmp_path / "core.db")
    await store.initialize()
    kernel = CaseKernel(store)
    case = await kernel.create_case("CASE-OUT", "CUST-1", "cs_refund", "1")
    case = await kernel.commit_fact(
        case.case_id,
        FactProposal(
            name="order_id",
            value="ORD-1",
            authority=FactAuthority.VERIFIED,
            source="orders",
            evidence_ref="orders:ORD-1:v1",
        ),
        case.version,
    )
    action = await kernel.authorize_action(
        ActionCommand(
            action="issue_refund",
            case_id=case.case_id,
            policy_package_id="refund@1:NAM",
            actor_id="rep-1",
            idempotency_key="refund:ORD-1",
            parameters={"order_id": "ORD-1"},
            parameter_fact_refs={"order_id": "order_id"},
            required_fact_authority={"order_id": FactAuthority.VERIFIED},
            consent_evidence_ref="message:yes",
        ),
        case.version,
    )
    pending = await store.list_outbox(OutboxStatus.PENDING)
    connector = Connector()
    worker = ActionDeliveryWorker(store, ActionGateway(kernel, {"issue_refund": connector}))

    first = await worker.run_once()
    second = await worker.run_once()

    assert len(pending) == 1
    assert pending[0].aggregate_id == action.action_id
    assert first.completed == 1
    assert second.claimed == 0
    assert connector.calls == 1
    events = await store.list_action_events(action.action_id)
    assert [event["status"] for event in events] == [
        "requested",
        "authorized",
        "dispatched",
        "succeeded",
    ]


@pytest.mark.asyncio
async def test_stale_dispatched_action_reconciles_after_process_crash_without_redispatch(tmp_path):
    class Connector:
        dispatch_calls = 0
        reconcile_calls = 0

        async def dispatch(self, command):
            self.dispatch_calls += 1
            raise AssertionError("stale dispatch must not be repeated")

        async def reconcile(self, command, prior):
            self.reconcile_calls += 1
            return ConnectorOutcome.succeeded({"provider_ref": "P-CRASH"})

    store = SQLiteCoreStore(tmp_path / "crash.db")
    await store.initialize()
    kernel = CaseKernel(store)
    case = await kernel.create_case("CASE-CRASH", "CUST-1", "cs_refund", "1")
    case = await kernel.commit_fact(
        case.case_id,
        FactProposal(
            name="order_id",
            value="ORD-CRASH",
            authority=FactAuthority.VERIFIED,
            source="orders",
            evidence_ref="orders:ORD-CRASH",
        ),
        case.version,
    )
    action = await kernel.authorize_action(
        ActionCommand(
            action="issue_refund",
            case_id=case.case_id,
            policy_package_id="refund@1:NAM",
            actor_id="rep-1",
            idempotency_key="refund:ORD-CRASH",
            parameters={"order_id": "ORD-CRASH"},
            parameter_fact_refs={"order_id": "order_id"},
            required_fact_authority={"order_id": FactAuthority.VERIFIED},
            consent_evidence_ref="message:yes",
        ),
        case.version,
    )
    claimed, did_claim = await store.claim_action(action.action_id)
    assert did_claim and claimed.status is ActionStatus.DISPATCHED

    connector = Connector()
    gateway = ActionGateway(kernel, {"issue_refund": connector})
    run = await ReconciliationWorker(
        store, gateway, dispatch_stale_seconds=0
    ).run_once()
    result = await store.get_action(action.action_id)
    assert run.completed == 1
    assert result is not None and result.status is ActionStatus.RECONCILED
    assert connector.dispatch_calls == 0
    assert connector.reconcile_calls == 1
    with pytest.raises(ValueError, match="Invalid action transition"):
        await kernel.record_outcome(
            action.action_id, ActionStatus.FAILED, {"reason": "late overwrite"}
        )


@pytest.mark.asyncio
async def test_provider_scoped_message_ids_do_not_collide(tmp_path):
    store = SQLiteCoreStore(tmp_path / "inbox.db")
    await store.initialize()
    base = {"message_id": "123", "text": "hello"}
    assert await store.accept_message({**base, "provider_id": "chat-a"}) is True
    assert await store.accept_message({**base, "provider_id": "chat-b"}) is True
    assert await store.accept_message({**base, "provider_id": "chat-a"}) is False


@pytest.mark.asyncio
async def test_sequence_gaps_are_quarantined_until_provider_resends_in_order(tmp_path):
    store = SQLiteCoreStore(tmp_path / "ordering.db")
    await store.initialize()
    common = {"provider_id": "chat-a", "conversation_id": "CONV-1", "text": "x"}
    first = await store.accept_message_result(
        {**common, "message_id": "M-1", "sequence": 1}
    )
    gap = await store.accept_message_result(
        {**common, "message_id": "M-3", "sequence": 3}
    )
    middle = await store.accept_message_result(
        {**common, "message_id": "M-2", "sequence": 2}
    )
    replay = await store.accept_message_result(
        {**common, "message_id": "M-3", "sequence": 3}
    )

    assert first["status"] == "accepted"
    assert gap["status"] == "quarantined"
    assert middle["status"] == "accepted"
    assert replay["status"] == "accepted"
    assert await store.list_quarantined_messages() == []


@pytest.mark.asyncio
async def test_policy_approval_and_activation_survive_restart(tmp_path):
    repository = SQLitePolicyRepository(tmp_path / "policies.db")
    signer = PolicySigner(b"durable-test-key", key_id="test-key-2026")
    registry = PolicyRegistry(signer)
    service = PolicyService(repository, signer, registry)
    draft = PolicyPackage(
        package_id="store-credit@1:NAM",
        procedure_id="cs_refund",
        version="1",
        jurisdiction="NAM",
        author="author-a",
        rules={"maximum": 250},
    )

    await service.create_draft(draft)
    approved = await service.approve(draft.package_id, "approver-b")
    active = await service.activate(draft.package_id)

    restarted_registry = PolicyRegistry(signer)
    await PolicyService(repository, signer, restarted_registry).hydrate()
    restored = restarted_registry.require_active(draft.package_id)
    assert approved.signing_key_id == "test-key-2026"
    assert active.lifecycle is PolicyLifecycle.ACTIVE
    assert restored == active


@pytest.mark.asyncio
async def test_action_authorized_before_policy_retirement_dispatches_after_restart(tmp_path):
    class Connector:
        async def dispatch(self, command):
            return ConnectorOutcome.succeeded({"provider_ref": "P-DELAYED"})

        async def reconcile(self, command, prior):
            return ConnectorOutcome.succeeded(prior or {})

    store = SQLiteCoreStore(tmp_path / "delayed-core.db")
    await store.initialize()
    kernel = CaseKernel(store)
    await kernel.create_case("CASE-DELAYED", "CUST-1", "cs_refund", "1")
    repository = SQLitePolicyRepository(tmp_path / "delayed-policy.db")
    signer = PolicySigner(b"delayed-policy-key")
    registry = PolicyRegistry(signer)
    service = PolicyService(repository, signer, registry)

    for version in ("1", "2"):
        draft = PolicyPackage(
            package_id=f"refund@{version}:NAM",
            procedure_id="cs_refund",
            version=version,
            jurisdiction="NAM",
            author=f"author-{version}",
            rules={"allowed_actions": ["escalate_to_supervisor"]},
        )
        await service.create_draft(draft)
        await service.approve(draft.package_id, f"approver-{version}")
        if version == "1":
            await service.activate(draft.package_id)

    gateway = ActionGateway(
        kernel, {"escalate_to_supervisor": Connector()}, policy_registry=registry
    )
    action = await gateway.authorize(
        ActionCommand(
            action="escalate_to_supervisor",
            case_id="CASE-DELAYED",
            policy_package_id="refund@1:NAM",
            actor_id="rep-1",
            idempotency_key="escalation:CASE-DELAYED",
            parameters={"reason": "manual review", "priority": "high"},
            parameter_fact_refs={},
            required_fact_authority={},
        ),
        expected_version=0,
    )
    await service.activate("refund@2:NAM")

    restarted_registry = PolicyRegistry(signer)
    await PolicyService(repository, signer, restarted_registry).hydrate()
    restarted_gateway = ActionGateway(
        kernel,
        {"escalate_to_supervisor": Connector()},
        policy_registry=restarted_registry,
    )
    result = await restarted_gateway.dispatch(action)
    assert result.status is ActionStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_chat_and_ivr_use_the_same_turn_pipeline_and_response_contract(tmp_path):
    calls = []

    async def processor(context, text):
        calls.append((context.channel, text))
        return GeneratedTurn(text=f"safe:{text}", risk=RiskLevel.CONSEQUENTIAL)

    store = SQLiteCoreStore(tmp_path / "turns.db")
    await store.initialize()
    service = ConversationService(ConversationRuntime(store), processor)
    common = {
        "actor_id": "rep-1",
        "actor_role": "customer_service_rep",
        "actor_permissions": ["customer:read"],
        "owner_id": "actor:rep-1:customer:CUST-1",
    }
    chat = await service.process_turn(
        MessageEnvelope(
            provider_id="chat-provider",
            message_id="M-1",
            conversation_id="CONV-1",
            customer_id="CUST-1",
            channel=ChannelKind.CHAT,
            text="hello",
        ),
        **common,
    )
    ivr = await service.process_turn(
        MessageEnvelope(
            provider_id="voice-provider",
            message_id="M-1",
            conversation_id="CONV-2",
            customer_id="CUST-1",
            channel=ChannelKind.IVR,
            text="hello",
            capabilities={"requires_readback": True},
        ),
        **common,
    )

    assert calls == [(ChannelKind.CHAT, "hello"), (ChannelKind.IVR, "hello")]
    assert chat.may_stream is False
    assert ivr.requires_readback is True


@pytest.mark.asyncio
async def test_typed_action_service_rejects_caller_data_that_differs_from_upstream(tmp_path):
    store = SQLiteCoreStore(tmp_path / "typed-core.db")
    await store.initialize()
    kernel = CaseKernel(store)
    connector = SQLiteSandboxActionConnector(tmp_path / "typed-upstream.db")
    await connector.put_resource(
        "order",
        "ORD-9",
        {"order_id": "ORD-9", "customer_id": "CUST-9", "amount": 80.0},
    )
    signer = PolicySigner(b"action-policy-key")
    active = signer.activate(
        signer.approve(
            PolicyPackage(
                package_id="store-credit@1:NAM",
                procedure_id="cs_refund",
                version="1",
                jurisdiction="NAM",
                author="author",
                rules={"allowed_actions": ["issue_store_credit"]},
            ),
            "approver",
        )
    )
    registry = PolicyRegistry(signer)
    registry.load(active)
    gateway = ActionGateway(
        kernel, {"issue_store_credit": connector}, policy_registry=registry
    )
    service = ConsequentialActionService(kernel, gateway, connector)
    request = ConsequentialActionRequest.model_validate(
        {
            "case_id": "CASE-9",
            "customer_id": "CUST-9",
            "procedure_id": "cs_refund",
            "procedure_version": "1",
            "policy_package_id": active.package_id,
            "idempotency_key": "store-credit:ORD-9",
            "resource": {"resource_type": "order", "resource_id": "ORD-9"},
            "payload": {
                "action": "issue_store_credit",
                "order_id": "ORD-9",
                "customer_id": "CUST-9",
                "amount": 999.0,
                "currency": "USD",
                "reason": "outside refund window",
            },
            "consent_evidence_ref": "message:yes",
        }
    )

    with pytest.raises(ValueError, match="does not match"):
        await service.submit(request, actor_id="rep-1")

    accepted = request.model_copy(
        update={"payload": request.payload.model_copy(update={"amount": 80.0})}
    )
    result = await service.submit(accepted, actor_id="rep-1")
    assert result.status is ActionStatus.SUCCEEDED
    assert result.outcome["simulated"] is True

    conflicting = accepted.model_copy(
        update={
            "case_id": "CASE-OTHER",
            "customer_id": "CUST-OTHER",
            "payload": accepted.payload.model_copy(update={"customer_id": "CUST-OTHER"}),
        }
    )
    with pytest.raises(ValueError, match="different action request"):
        await service.submit(conflicting, actor_id="rep-2")


def test_nam_ivr_consent_controls_are_configurable_and_fail_closed_when_enforced():
    profile = JurisdictionProfile(
        profile_id="NAM-test",
        regions=["US-ND"],
        recording_consent_required=True,
        transcription_consent_required=False,
    )
    blocked = JurisdictionGuard(profile, enforce=True).evaluate_inbound(
        channel=ChannelKind.IVR,
        consent_snapshot={},
    )
    observed = JurisdictionGuard(profile, enforce=False).evaluate_inbound(
        channel=ChannelKind.IVR,
        consent_snapshot={},
    )
    assert blocked.allowed is False
    assert blocked.blocks == ["recording_consent_missing"]
    assert observed.allowed is True
    assert observed.warnings == ["recording_consent_missing"]


def test_every_consequential_catalog_operation_has_a_closed_gateway_specification():
    catalog_actions = {
        name for name, control in TOOL_CATALOG.items() if control.consequential
    }
    assert set(ACTION_SPECIFICATIONS) == catalog_actions
    assert set(ACTION_PERMISSIONS) == catalog_actions - {"issue_refund"}


def test_policy_key_rotation_can_verify_history_without_using_old_key_for_signing():
    old = PolicySigner(b"old-policy-key", key_id="key-2025")
    active = old.activate(
        old.approve(
            PolicyPackage(
                package_id="refund@rotation:NAM",
                procedure_id="cs_refund",
                version="rotation",
                jurisdiction="NAM",
                author="author",
                rules={"allowed_actions": ["issue_refund"]},
            ),
            "approver",
        )
    )
    rotated = PolicySigner(
        b"new-policy-key",
        key_id="key-2026",
        verification_keys={"key-2025": b"old-policy-key"},
    )
    assert rotated.verify(active) is True
    retired = rotated.retire(active)
    assert retired.signing_key_id == "key-2026"
    assert retired.activation_signature == active.activation_signature
    assert rotated.verify(retired) is True


def test_deployment_adapter_factory_uses_explicit_dotted_callable_contract():
    factory = load_factory("workflow_engine.core.kernel:create_core_store")
    assert factory is not None
    with pytest.raises(ValueError, match="package.module:callable"):
        load_factory("not-a-dotted-factory")


@pytest.mark.asyncio
async def test_provider_bundle_initializes_each_unique_adapter_once():
    class Adapter:
        def __init__(self):
            self.calls = 0

        async def initialize(self):
            self.calls += 1

    adapter = Adapter()
    bundle = ProviderBundle(
        stt=adapter, tts=adapter, telephony=adapter, chat=adapter,
        handoff=adapter, action=adapter, resources=adapter,
    )
    assert validate_provider_bundle(bundle) is bundle
    await bundle.initialize()
    assert adapter.calls == 1
