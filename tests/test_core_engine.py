"""End-to-end tests for the authoritative modular-monolith core."""

import asyncio
import pytest
import pytest_asyncio

from workflow_engine.core.kernel import (
    ActionCommand,
    ActionStatus,
    CaseConflict,
    CaseKernel,
    FactAuthority,
    FactProposal,
    SQLiteCoreStore,
    create_core_store,
)
from workflow_engine.core.policy import PolicyLifecycle, PolicyPackage, PolicyRegistry, PolicySigner
from workflow_engine.core.gateway import ActionGateway, ConnectorOutcome
from workflow_engine.core.domains import OrderSnapshot, RefundDecisionService, RegEDecisionService
from workflow_engine.core.service import CoreEngine
from workflow_engine.core.routing import ProcedureRouter
from workflow_engine.core.adk2 import CandidateProposal, build_bounded_interaction_graph, validate_proposal
from workflow_engine.core.verification import ReplayHarness, RolloutGate
from workflow_engine.conversation.runtime import (
    ChannelKind,
    ConversationRuntime,
    HandoffStatus,
    MessageEnvelope,
)
from workflow_engine.conversation.contracts import ResponseContract, RiskLevel
from workflow_engine.channels.ivr import IvrAdapter


@pytest.fixture
def policy_signer():
    return PolicySigner(b"test-signing-key")


@pytest_asyncio.fixture
async def kernel(tmp_path):
    store = SQLiteCoreStore(tmp_path / "core.db")
    await store.initialize()
    return CaseKernel(store)


@pytest.mark.asyncio
async def test_verified_fact_and_idempotent_action_lifecycle(kernel):
    await kernel.create_case("CASE-1", "CUST-456", "cs_refund", "1.0.0")
    case = await kernel.commit_fact(
        "CASE-1",
        FactProposal(
            name="order_id",
            value="ORD-123",
            authority=FactAuthority.VERIFIED,
            source="orders_db",
            evidence_ref="order:ORD-123",
        ),
        expected_version=0,
    )

    command = ActionCommand(
        action="issue_refund",
        case_id="CASE-1",
        policy_package_id="refund@1.0.0",
        actor_id="rep-1",
        idempotency_key="refund:ORD-123",
        consent_evidence_ref="test:consent",
        parameters={"order_id": "ORD-123", "amount": 79.99},
        parameter_fact_refs={"order_id": "order_id"},
        required_fact_authority={"order_id": FactAuthority.VERIFIED},
    )
    first = await kernel.authorize_action(command, expected_version=case.version)
    duplicate = await kernel.authorize_action(command, expected_version=case.version + 1)

    assert first.action_id == duplicate.action_id
    assert first.status is ActionStatus.AUTHORIZED


@pytest.mark.asyncio
async def test_asserted_fact_cannot_authorize_verified_precondition(kernel):
    await kernel.create_case("CASE-2", "CUST-456", "cs_refund", "1.0.0")
    case = await kernel.commit_fact(
        "CASE-2",
        FactProposal(
            name="order_id",
            value="ORD-123",
            authority=FactAuthority.ASSERTED,
            source="customer",
            evidence_ref="message:m1",
        ),
        expected_version=0,
    )
    command = ActionCommand(
        action="issue_refund",
        case_id="CASE-2",
        policy_package_id="refund@1.0.0",
        actor_id="rep-1",
        idempotency_key="refund:ORD-123",
        consent_evidence_ref="test:consent",
        parameters={"order_id": "ORD-123"},
        parameter_fact_refs={"order_id": "order_id"},
        required_fact_authority={"order_id": FactAuthority.VERIFIED},
    )

    with pytest.raises(ValueError, match="authority"):
        await kernel.authorize_action(command, expected_version=case.version)


@pytest.mark.asyncio
async def test_case_optimistic_conflict(kernel):
    await kernel.create_case("CASE-3", "CUST-456", "cs_refund", "1.0.0")
    await kernel.commit_fact(
        "CASE-3",
        FactProposal(
            name="order_id",
            value="ORD-123",
            authority=FactAuthority.VERIFIED,
            source="orders_db",
            evidence_ref="order:ORD-123",
        ),
        expected_version=0,
    )
    with pytest.raises(CaseConflict):
        await kernel.commit_fact(
            "CASE-3",
            FactProposal(
                name="reason",
                value="damaged",
                authority=FactAuthority.ASSERTED,
                source="customer",
                evidence_ref="message:m2",
            ),
            expected_version=0,
        )


def test_policy_requires_separate_approver_and_valid_signature(policy_signer):
    package = PolicyPackage(
        package_id="refund@1.0.0",
        procedure_id="cs_refund",
        version="1.0.0",
        jurisdiction="NAM",
        author="policy-author",
        rules={"refund_window_days": 30},
    )
    with pytest.raises(ValueError, match="separate"):
        policy_signer.approve(package, approver="policy-author")

    approved = policy_signer.approve(package, approver="risk-approver")
    assert approved.lifecycle is PolicyLifecycle.APPROVED
    assert policy_signer.verify(approved)
    active = policy_signer.activate(approved)
    registry = PolicyRegistry(policy_signer)
    registry.load(active)
    assert registry.require_active(active.package_id) == active

    tampered = active.model_copy(update={"rules": {"refund_window_days": 999}})
    with pytest.raises(ValueError, match="valid active"):
        PolicyRegistry(policy_signer).load(tampered)


@pytest.mark.asyncio
async def test_chat_and_ivr_share_dedupe_and_truthful_handoff(tmp_path):
    store = SQLiteCoreStore(tmp_path / "conversation.db")
    await store.initialize()
    runtime = ConversationRuntime(store)
    chat = MessageEnvelope(
        message_id="provider-1",
        conversation_id="CONV-1",
        customer_id="CUST-456",
        channel=ChannelKind.CHAT,
        text="I need help",
    )
    assert await runtime.accept(chat) is True
    assert await runtime.accept(chat) is False

    ivr = chat.model_copy(update={"message_id": "provider-2", "channel": ChannelKind.IVR})
    assert await runtime.accept(ivr) is True

    handoff = await runtime.request_handoff("CONV-1", "CASE-1", {"summary": "needs agent"})
    assert handoff.status is HandoffStatus.REQUESTED
    accepted = await runtime.accept_handoff(handoff.handoff_id, "agent-7")
    assert accepted.status is HandoffStatus.ACCEPTED
    assert accepted.assigned_agent_id == "agent-7"


def test_sqlite_is_default_but_other_database_adapters_are_configurable(tmp_path):
    sqlite = create_core_store(f"sqlite+aiosqlite:///{tmp_path / 'default.db'}")
    assert isinstance(sqlite, SQLiteCoreStore)

    sentinel = object()
    configured = create_core_store(
        "postgresql+asyncpg://db/core",
        adapters={"postgresql": lambda _url: sentinel},
    )
    assert configured is sentinel


def test_refund_and_reg_e_decisions_are_deterministic():
    refund = RefundDecisionService(refund_window_days=30).evaluate(
        order_id="ORD-123",
        authenticated_customer_id="CUST-456",
        order_customer_id="CUST-456",
        order_status="delivered",
        days_since_delivery=12,
        amount=79.99,
    )
    assert refund.eligible is True
    assert refund.idempotency_key == "refund:ORD-123"

    denied = RegEDecisionService().evaluate("debit_card", days_since_noticed=61, amount=400)
    assert denied.eligible is False
    assert denied.liability_tier == "tier_3"


@pytest.mark.asyncio
async def test_gateway_records_unknown_then_reconciles_without_redispatch(kernel):
    class AmbiguousConnector:
        dispatch_count = 0

        async def dispatch(self, command):
            self.dispatch_count += 1
            return ConnectorOutcome.unknown({"provider_ref": "p-1"})

        async def reconcile(self, command, prior):
            return ConnectorOutcome.succeeded({"provider_ref": "p-1", "settled": True})

    await kernel.create_case("CASE-4", "CUST-456", "cs_refund", "1.0.0")
    case = await kernel.commit_fact(
        "CASE-4",
        FactProposal(
            name="order_id", value="ORD-123", authority=FactAuthority.VERIFIED,
            source="orders_db", evidence_ref="order:ORD-123",
        ),
        expected_version=0,
    )
    command = ActionCommand(
        action="issue_refund", case_id="CASE-4", policy_package_id="refund@1.0.0",
        actor_id="rep-1", idempotency_key="refund:ORD-123",
        consent_evidence_ref="test:consent",
        parameters={"order_id": "ORD-123"}, parameter_fact_refs={"order_id": "order_id"},
        required_fact_authority={"order_id": FactAuthority.VERIFIED},
    )
    action = await kernel.authorize_action(command, case.version)
    connector = AmbiguousConnector()
    gateway = ActionGateway(kernel, {"issue_refund": connector})

    unknown = await gateway.dispatch(action)
    reconciled = await gateway.reconcile(unknown)

    assert unknown.status is ActionStatus.UNKNOWN
    assert reconciled.status is ActionStatus.RECONCILED
    assert connector.dispatch_count == 1


@pytest.mark.asyncio
async def test_concurrent_gateway_dispatch_claims_action_once(kernel):
    class CountingConnector:
        dispatch_count = 0

        async def dispatch(self, command):
            self.dispatch_count += 1
            await asyncio.sleep(0.01)
            return ConnectorOutcome.succeeded({"ok": True})

        async def reconcile(self, command, prior):
            return ConnectorOutcome.succeeded(prior or {})

    await kernel.create_case("CASE-CONCURRENT", "CUST-456", "cs_refund", "1.0.0")
    case = await kernel.commit_fact(
        "CASE-CONCURRENT",
        FactProposal(
            name="order_id", value="ORD-123", authority=FactAuthority.VERIFIED,
            source="orders_db", evidence_ref="order:ORD-123",
        ),
        0,
    )
    action = await kernel.authorize_action(
        ActionCommand(
            action="issue_refund", case_id="CASE-CONCURRENT",
            policy_package_id="refund@1.0.0", actor_id="rep-1",
            idempotency_key="refund:concurrent", consent_evidence_ref="test:consent",
            parameters={"order_id": "ORD-123"},
            parameter_fact_refs={"order_id": "order_id"},
            required_fact_authority={"order_id": FactAuthority.VERIFIED},
        ),
        case.version,
    )
    connector = CountingConnector()
    gateway = ActionGateway(kernel, {"issue_refund": connector})
    await asyncio.gather(gateway.dispatch(action), gateway.dispatch(action))
    assert connector.dispatch_count == 1


@pytest.mark.asyncio
async def test_connector_exception_becomes_unknown_not_false_failure(kernel):
    class BrokenConnector:
        async def dispatch(self, command):
            raise TimeoutError("ambiguous provider timeout")

        async def reconcile(self, command, prior):
            return ConnectorOutcome.unknown(prior or {})

    await kernel.create_case("CASE-TIMEOUT", "CUST-456", "cs_refund", "1.0.0")
    case = await kernel.commit_fact(
        "CASE-TIMEOUT",
        FactProposal(
            name="order_id", value="ORD-123", authority=FactAuthority.VERIFIED,
            source="orders_db", evidence_ref="order:ORD-123",
        ),
        0,
    )
    action = await kernel.authorize_action(
        ActionCommand(
            action="issue_refund", case_id="CASE-TIMEOUT",
            policy_package_id="refund@1.0.0", actor_id="rep-1",
            idempotency_key="refund:timeout", consent_evidence_ref="test:consent",
            parameters={"order_id": "ORD-123"},
            parameter_fact_refs={"order_id": "order_id"},
            required_fact_authority={"order_id": FactAuthority.VERIFIED},
        ),
        case.version,
    )
    result = await ActionGateway(
        kernel, {"issue_refund": BrokenConnector()}
    ).dispatch(action)
    assert result.status is ActionStatus.UNKNOWN
    assert result.outcome["error_type"] == "TimeoutError"


def test_ivr_low_confidence_cannot_become_verified_fact():
    turn = IvrAdapter(min_verification_confidence=0.9).normalize(
        provider_message_id="call-1:turn-1",
        conversation_id="call-1",
        customer_id="CUST-456",
        transcript="refund order one two three",
        asr_confidence=0.71,
        interrupted=False,
    )
    assert turn.proposed_authority is FactAuthority.ASSERTED
    assert turn.requires_readback is True


def test_response_contract_holds_consequential_claims_on_chat_and_ivr():
    contract = ResponseContract()
    for channel in (ChannelKind.CHAT, ChannelKind.IVR):
        decision = contract.evaluate(
            channel=channel,
            risk=RiskLevel.CONSEQUENTIAL,
            authoritative_status=None,
        )
        assert decision.may_stream is False
        assert decision.may_claim_success is False


def test_router_locks_versions_and_composes_compound_intents():
    router = ProcedureRouter(
        {
            "cs_refund": {"version": "1.0.0", "keywords": {"refund", "return"}},
            "cs_eft_dispute": {"version": "1.1.0", "keywords": {"unauthorized", "debit"}},
        }
    )
    route = router.route("refund an unauthorized debit", current=None)
    assert route.primary_procedure == "cs_eft_dispute"
    assert route.subprocedures == ["cs_refund"]

    locked = router.route("refund", current=route)
    assert locked.versions == route.versions


def test_adk2_graph_outputs_proposals_not_verified_facts():
    proposal = validate_proposal(
        CandidateProposal(
            intent="refund", extracted_facts={"order_id": "ORD-123"},
            evidence_spans={"order_id": "characters:7-14"},
        )
    )
    assert proposal.fact_authority is FactAuthority.ASSERTED
    graph = build_bounded_interaction_graph()
    assert graph.name == "bounded_interaction_graph"
    assert not getattr(graph, "tools", None)


def test_replay_and_rollout_gate_separate_determinism_from_model_quality():
    service = RegEDecisionService()
    inputs = {"payment_method": "debit_card", "days_since_noticed": 2, "amount": 100}
    expected = service.evaluate(**inputs)
    result = ReplayHarness().replay(service.evaluate, inputs, expected)
    assert result.deterministic is True
    assert RolloutGate(
        procedure_id="cs_eft_dispute", channel="ivr", risk_tier="regulated"
    ).may_advance()


@pytest.mark.asyncio
async def test_core_engine_refund_vertical_slice_reloads_verified_snapshot(kernel):
    class RefundConnector:
        async def dispatch(self, command):
            return ConnectorOutcome.succeeded({"refund_id": "REF-123"})

        async def reconcile(self, command, prior):
            return ConnectorOutcome.succeeded(prior or {})

    gateway = ActionGateway(kernel, {"issue_refund": RefundConnector()})
    engine = CoreEngine(kernel, gateway, RefundDecisionService())
    result = await engine.process_refund(
        case_id="CASE-VERTICAL-1",
        authenticated_customer_id="CUST-456",
        actor_id="rep-1",
        policy_package_id="refund@1.0.0",
        procedure_version="1.0.0",
        consent_evidence_ref="test:consent",
        order=OrderSnapshot(
            order_id="ORD-123", customer_id="CUST-456", status="delivered",
            days_since_delivery=4, amount=79.99, payment_method="credit_card",
            evidence_ref="orders-db:ORD-123:v7",
        ),
    )
    assert result.status is ActionStatus.SUCCEEDED
    assert result.outcome == {"refund_id": "REF-123"}
