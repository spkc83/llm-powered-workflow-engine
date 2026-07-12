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


class HandoffStatus(str, Enum):
    REQUESTED = "requested"
    ACCEPTED = "accepted"
    TIMED_OUT = "timed_out"
    FAILED = "failed"
    RESOLVED = "resolved"


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
        updated = await self.store.update_handoff(
            handoff_id, HandoffStatus.ACCEPTED.value, agent_id
        )
        return HandoffRecord(**updated)
