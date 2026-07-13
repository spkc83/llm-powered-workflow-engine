import pytest

from workflow_engine.actions import (
    ActionBridge,
    ActionConfirmationContext,
    ActionIntent,
    TrustedActionContext,
)
from workflow_engine.core.action_service import ConsequentialActionService
from workflow_engine.core.gateway import ActionGateway
from workflow_engine.core.gateway import ResolvedActionConnector
from workflow_engine.core.kernel import (
    ActionProposalStatus,
    ActionStatus,
    CaseKernel,
    SQLiteCoreStore,
)
from workflow_engine.integrations.sandbox import SQLiteSandboxActionConnector


@pytest.fixture
def context() -> TrustedActionContext:
    return TrustedActionContext(
        actor_id="rep-1",
        customer_id="CUST-1",
        case_id="CASE-1",
        procedure_id="cs_refund",
        procedure_version="1",
        policy_package_id="refund@1:NAM",
        conversation_id="CONV-1",
        message_id="MSG-1",
        connector_binding_id="sqlite-demo-refunds",
        connector_binding_version="1",
        contract_version="v1",
    )


@pytest.fixture
def confirmation() -> ActionConfirmationContext:
    return ActionConfirmationContext(
        actor_id="rep-1",
        customer_id="CUST-1",
        consent_evidence_ref="chat:MSG-2:confirm",
    )


async def _bridge(tmp_path) -> tuple[ActionBridge, SQLiteCoreStore]:
    store = SQLiteCoreStore(tmp_path / "core.db")
    await store.initialize()
    kernel = CaseKernel(store)
    connector = SQLiteSandboxActionConnector(tmp_path / "sandbox.db")
    await connector.put_resource(
        "order",
        "ORD-1",
        {
            "order_id": "ORD-1",
            "customer_id": "CUST-1",
            "status": "delivered",
            "days_since_delivery": 3,
            "amount": 42.5,
            "currency": "USD",
            "payment_method": "credit_card",
        },
    )
    gateway = ActionGateway(kernel, {"issue_refund": connector})
    service = ConsequentialActionService(kernel, gateway, connector)
    return (
        ActionBridge(kernel=kernel, action_service=service, resources=connector),
        store,
    )


@pytest.mark.asyncio
async def test_bridge_confirms_refund_through_typed_gateway(
    tmp_path, context, confirmation
):
    bridge, store = await _bridge(tmp_path)

    proposal = await bridge.propose(
        ActionIntent(
            action="issue_refund",
            arguments={"order_id": "ORD-1", "reason": "item not received"},
        ),
        context=context,
    )
    assert proposal.status is ActionProposalStatus.PENDING
    assert proposal.resource_version == 1
    assert proposal.customer_id == "CUST-1"
    assert proposal.connector_binding_id == "sqlite-demo-refunds"
    assert proposal.payload == {
        "action": "issue_refund",
        "order_id": "ORD-1",
        "customer_id": "CUST-1",
        "refund_amount": 42.5,
        "currency": "USD",
        "payment_method": "credit_card",
        "reason": "item not received",
    }

    confirmed = await bridge.confirm(proposal.proposal_id, context=confirmation)
    assert confirmed.status is ActionProposalStatus.CONFIRMED
    assert confirmed.action_id is not None
    action = await store.get_action(confirmed.action_id)
    assert action is not None
    assert action.status is ActionStatus.SUCCEEDED
    assert action.command.connector_binding_id == "legacy"
    assert action.command.connector_binding_version == "1"
    assert action.command.contract_version == "1"
    assert action.command.parameters["refund_amount"] == 42.5

    replay = await bridge.confirm(proposal.proposal_id, context=confirmation)
    assert replay.action_id == confirmed.action_id


@pytest.mark.asyncio
async def test_bridge_blocks_cross_customer_proposal_access(
    tmp_path, context, confirmation
):
    bridge, _store = await _bridge(tmp_path)
    proposal = await bridge.propose(
        ActionIntent(action="issue_refund", arguments={"order_id": "ORD-1"}),
        context=context,
    )

    with pytest.raises(ValueError, match="does not belong"):
        await bridge.confirm(
            proposal.proposal_id,
            context=confirmation.model_copy(update={"customer_id": "CUST-OTHER"}),
        )


@pytest.mark.asyncio
async def test_bridge_blocks_cross_actor_confirmation(
    tmp_path, context, confirmation
):
    bridge, _store = await _bridge(tmp_path)
    proposal = await bridge.propose(
        ActionIntent(action="issue_refund", arguments={"order_id": "ORD-1"}),
        context=context,
    )

    with pytest.raises(ValueError, match="actor"):
        await bridge.confirm(
            proposal.proposal_id,
            context=confirmation.model_copy(update={"actor_id": "rep-2"}),
        )


@pytest.mark.asyncio
async def test_bridge_requires_consent_evidence_before_submit(
    tmp_path, context, confirmation
):
    bridge, _store = await _bridge(tmp_path)
    proposal = await bridge.propose(
        ActionIntent(action="issue_refund", arguments={"order_id": "ORD-1"}),
        context=context,
    )

    with pytest.raises(ValueError, match="consent evidence"):
        await bridge.confirm(
            proposal.proposal_id,
            context=confirmation.model_copy(update={"consent_evidence_ref": None}),
        )


@pytest.mark.asyncio
async def test_bridge_prepares_generic_authoritative_action_payload(
    tmp_path, context
):
    bridge, _store = await _bridge(tmp_path)
    await bridge.resources.put_resource(
        "order",
        "ORD-2",
        {
            "order_id": "ORD-2",
            "customer_id": "CUST-1",
            "amount": 25.0,
            "currency": "USD",
        },
    )

    proposal = await bridge.propose(
        ActionIntent(
            action="issue_store_credit",
            arguments={
                "order_id": "MODEL-SUPPLIED",
                "customer_id": "WRONG-CUSTOMER",
                "amount": 999.0,
                "currency": "EUR",
                "reason": "outside refund window",
            },
            resource_type="order",
            resource_id="ORD-2",
        ),
        context=context,
    )

    assert proposal.payload == {
        "action": "issue_store_credit",
        "order_id": "ORD-2",
        "customer_id": "CUST-1",
        "amount": 25.0,
        "currency": "USD",
        "reason": "outside refund window",
    }
    assert proposal.safe_preview["parameters"]["amount"] == 25.0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "resource_type", "resource_id", "payload", "arguments"),
    [
        (
            "issue_store_credit",
            "order",
            "ORD-OTHER",
            {
                "order_id": "ORD-OTHER",
                "customer_id": "CUST-OTHER",
                "amount": 25.0,
                "currency": "USD",
            },
            {"reason": "service recovery"},
        ),
        (
            "file_eft_dispute",
            "transaction",
            "TXN-OTHER",
            {
                "transaction_id": "TXN-OTHER",
                "customer_id": "CUST-OTHER",
                "amount": 25.0,
            },
            {"dispute_type": "unauthorized"},
        ),
        (
            "issue_provisional_credit",
            "dispute",
            "DISP-OTHER",
            {
                "dispute_id": "DISP-OTHER",
                "customer_id": "CUST-OTHER",
                "amount": 25.0,
            },
            {},
        ),
    ],
)
async def test_bridge_rejects_authoritative_resource_owned_by_another_customer(
    tmp_path, context, action, resource_type, resource_id, payload, arguments
):
    bridge, _store = await _bridge(tmp_path)
    await bridge.resources.put_resource(resource_type, resource_id, payload)

    with pytest.raises(ValueError, match="serviced customer"):
        await bridge.propose(
            ActionIntent(
                action=action,
                arguments=arguments,
                resource_type=resource_type,
                resource_id=resource_id,
            ),
            context=context,
        )


@pytest.mark.asyncio
async def test_bridge_rejects_confirmation_after_resource_version_changes(
    tmp_path, context, confirmation
):
    bridge, _store = await _bridge(tmp_path)
    proposal = await bridge.propose(
        ActionIntent(action="issue_refund", arguments={"order_id": "ORD-1"}),
        context=context,
    )
    await bridge.resources.put_resource(
        "order",
        "ORD-1",
        {
            "order_id": "ORD-1",
            "customer_id": "CUST-1",
            "status": "delivered",
            "days_since_delivery": 3,
            "amount": 41.0,
            "currency": "USD",
            "payment_method": "credit_card",
        },
    )

    with pytest.raises(ValueError, match="version changed"):
        await bridge.confirm(proposal.proposal_id, context=confirmation)


@pytest.mark.asyncio
async def test_bridge_rejects_confirmation_after_connector_binding_changes(
    tmp_path, context, confirmation
):
    bridge, _store = await _bridge(tmp_path)

    class Resolver:
        version = "1"

        def resolve(self, action_name):
            return ResolvedActionConnector(
                action_name=action_name,
                binding_id="provider-refunds",
                binding_version=self.version,
                contract_version="v1",
                connector=bridge.resources,
            )

    resolver = Resolver()
    bridge.connector_resolver = resolver
    proposal = await bridge.propose(
        ActionIntent(action="issue_refund", arguments={"order_id": "ORD-1"}),
        context=context,
    )
    resolver.version = "2"

    with pytest.raises(ValueError, match="binding changed"):
        await bridge.confirm(proposal.proposal_id, context=confirmation)


@pytest.mark.asyncio
async def test_bridge_cancels_pending_proposal_once(tmp_path, context, confirmation):
    bridge, _store = await _bridge(tmp_path)
    proposal = await bridge.propose(
        ActionIntent(action="issue_refund", arguments={"order_id": "ORD-1"}),
        context=context,
    )

    cancelled = await bridge.cancel(proposal.proposal_id, context=confirmation)
    assert cancelled.status is ActionProposalStatus.CANCELLED

    replay = await bridge.cancel(proposal.proposal_id, context=confirmation)
    assert replay.status is ActionProposalStatus.CANCELLED
    with pytest.raises(ValueError, match="cancelled"):
        await bridge.confirm(proposal.proposal_id, context=confirmation)
