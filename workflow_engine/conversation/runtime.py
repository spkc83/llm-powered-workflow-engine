"""Transport-neutral inbox and human-handoff lifecycle for chat and IVR."""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from workflow_engine.core.kernel import CoreStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChannelKind(str, Enum):
    CHAT = "chat"
    IVR = "ivr"


class MessageEnvelope(BaseModel):
    provider_id: str = "local"
    message_id: str
    conversation_id: str
    customer_id: str
    channel: ChannelKind
    text: str
    locale: str = "en-US"
    timezone: str = "America/Chicago"
    sequence: int | None = None
    correlation_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    causation_id: str | None = None
    consent_snapshot: dict[str, Any] = Field(default_factory=dict)
    capabilities: dict[str, Any] = Field(default_factory=dict)


class MessageAcceptance(BaseModel):
    accepted: bool
    status: str
    reason: str | None = None


class HandoffStatus(str, Enum):
    REQUESTED = "requested"
    QUEUED = "queued"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"
    FAILED = "failed"
    REASSIGNED = "reassigned"
    CONNECTED = "connected"
    RESOLVED = "resolved"
    BOT_REENTRY = "bot_reentry"


class HandoffRecord(BaseModel):
    handoff_id: str
    conversation_id: str
    case_id: str
    context: dict[str, Any]
    status: HandoffStatus
    assigned_agent_id: str | None = None
    created_at: str
    updated_at: str


class ConversationRuntime:
    def __init__(self, store: CoreStore):
        self.store = store

    async def accept(self, envelope: MessageEnvelope) -> bool:
        """Persist once by provider message ID for both chat and IVR."""
        return await self.store.accept_message(envelope.model_dump(mode="json"))

    async def accept_result(self, envelope: MessageEnvelope) -> MessageAcceptance:
        result = await self.store.accept_message_result(envelope.model_dump(mode="json"))
        return MessageAcceptance(**result)

    async def request_handoff(
        self,
        conversation_id: str,
        case_id: str,
        context: dict[str, Any],
    ) -> HandoffRecord:
        now = _now()
        record = HandoffRecord(
            handoff_id=f"HO-{uuid.uuid4().hex}", conversation_id=conversation_id,
            case_id=case_id, context=context, status=HandoffStatus.REQUESTED,
            created_at=now, updated_at=now,
        )
        await self.store.create_handoff(record.model_dump(mode="json"))
        return record

    async def accept_handoff(self, handoff_id: str, agent_id: str) -> HandoffRecord:
        current = await self.store.get_handoff(handoff_id)
        if not current:
            raise KeyError(handoff_id)
        if current["status"] != HandoffStatus.REQUESTED.value:
            raise ValueError("Only requested handoffs can be accepted")
        updated = await self.store.transition_handoff(
            handoff_id,
            HandoffStatus.REQUESTED.value,
            HandoffStatus.ACCEPTED.value,
            agent_id,
        )
        return HandoffRecord(**updated)

    async def transition_handoff(
        self,
        handoff_id: str,
        status: HandoffStatus,
        agent_id: str | None = None,
    ) -> HandoffRecord:
        current = await self.store.get_handoff(handoff_id)
        if not current:
            raise KeyError(handoff_id)
        current_status = HandoffStatus(current["status"])
        allowed = {
            HandoffStatus.REQUESTED: {
                HandoffStatus.QUEUED,
                HandoffStatus.ACCEPTED,
                HandoffStatus.REJECTED,
                HandoffStatus.FAILED,
            },
            HandoffStatus.QUEUED: {
                HandoffStatus.ACCEPTED,
                HandoffStatus.TIMED_OUT,
                HandoffStatus.REASSIGNED,
                HandoffStatus.FAILED,
            },
            HandoffStatus.REASSIGNED: {
                HandoffStatus.ACCEPTED,
                HandoffStatus.TIMED_OUT,
                HandoffStatus.FAILED,
            },
            HandoffStatus.ACCEPTED: {
                HandoffStatus.CONNECTED,
                HandoffStatus.REASSIGNED,
                HandoffStatus.FAILED,
            },
            HandoffStatus.CONNECTED: {
                HandoffStatus.RESOLVED,
                HandoffStatus.BOT_REENTRY,
                HandoffStatus.FAILED,
            },
            HandoffStatus.RESOLVED: {HandoffStatus.BOT_REENTRY},
            HandoffStatus.TIMED_OUT: {HandoffStatus.REASSIGNED, HandoffStatus.BOT_REENTRY},
            HandoffStatus.REJECTED: {HandoffStatus.BOT_REENTRY},
            HandoffStatus.FAILED: {HandoffStatus.REASSIGNED, HandoffStatus.BOT_REENTRY},
            HandoffStatus.BOT_REENTRY: set(),
        }
        if status not in allowed[current_status]:
            raise ValueError(
                f"Invalid handoff transition: {current_status.value} -> {status.value}"
            )
        updated = await self.store.transition_handoff(
            handoff_id, current_status.value, status.value, agent_id
        )
        return HandoffRecord(**updated)
