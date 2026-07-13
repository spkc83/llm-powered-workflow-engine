"""Single application pipeline used by REST chat, WebSocket chat, and IVR turns."""

from typing import Any, Protocol

from pydantic import BaseModel, Field

from workflow_engine.conversation.contracts import ResponseContract, RiskLevel
from workflow_engine.conversation.runtime import ChannelKind, ConversationRuntime, MessageEnvelope


class TurnContext(BaseModel):
    actor_id: str
    actor_role: str
    actor_permissions: list[str]
    customer_id: str
    owner_id: str
    conversation_id: str
    message_id: str
    channel: ChannelKind
    locale: str
    timezone: str


class GeneratedTurn(BaseModel):
    text: str
    risk: RiskLevel = RiskLevel.INFORMATIONAL
    authoritative_status: str | None = None
    action_proposals: list[dict[str, Any]] = Field(default_factory=list)


class TurnResult(BaseModel):
    accepted: bool
    duplicate: bool
    quarantined: bool = False
    acceptance_status: str = "accepted"
    conversation_id: str
    message_id: str
    response: str | None
    risk: RiskLevel
    authoritative_status: str | None
    may_stream: bool
    may_claim_success: bool
    requires_approved_content: bool
    requires_readback: bool
    action_proposals: list[dict[str, Any]] = Field(default_factory=list)


class TurnProcessor(Protocol):
    async def __call__(self, context: TurnContext, text: str) -> GeneratedTurn: ...


class ConversationService:
    """Transport-neutral dedupe, generation, and response-contract boundary."""

    def __init__(
        self,
        runtime: ConversationRuntime,
        processor: TurnProcessor,
        response_contract: ResponseContract | None = None,
    ):
        self.runtime = runtime
        self.processor = processor
        self.response_contract = response_contract or ResponseContract()

    async def process_turn(
        self,
        envelope: MessageEnvelope,
        *,
        actor_id: str,
        actor_role: str,
        actor_permissions: list[str],
        owner_id: str,
    ) -> TurnResult:
        acceptance = await self.runtime.accept_result(envelope)
        if not acceptance.accepted:
            return TurnResult(
                accepted=False,
                duplicate=acceptance.status == "duplicate",
                quarantined=acceptance.status == "quarantined",
                acceptance_status=acceptance.status,
                conversation_id=envelope.conversation_id,
                message_id=envelope.message_id,
                response=None,
                risk=RiskLevel.INFORMATIONAL,
                authoritative_status=None,
                may_stream=False,
                may_claim_success=False,
                requires_approved_content=False,
                requires_readback=False,
                action_proposals=[],
            )
        context = TurnContext(
            actor_id=actor_id,
            actor_role=actor_role,
            actor_permissions=sorted(actor_permissions),
            customer_id=envelope.customer_id,
            owner_id=owner_id,
            conversation_id=envelope.conversation_id,
            message_id=envelope.message_id,
            channel=envelope.channel,
            locale=envelope.locale,
            timezone=envelope.timezone,
        )
        generated = await self.processor(context, envelope.text)
        decision = self.response_contract.evaluate(
            channel=envelope.channel,
            risk=generated.risk,
            authoritative_status=generated.authoritative_status,
        )
        input_requires_readback = bool(envelope.capabilities.get("requires_readback"))
        return TurnResult(
            accepted=True,
            duplicate=False,
            quarantined=False,
            acceptance_status="accepted",
            conversation_id=envelope.conversation_id,
            message_id=envelope.message_id,
            response=generated.text,
            risk=generated.risk,
            authoritative_status=generated.authoritative_status,
            may_stream=decision.may_stream,
            may_claim_success=decision.may_claim_success,
            requires_approved_content=decision.requires_approved_content,
            requires_readback=decision.requires_readback or input_requires_readback,
            action_proposals=generated.action_proposals,
        )
