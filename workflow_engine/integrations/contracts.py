"""Stable ports implemented by telephony, speech, chat, action, and queue vendors."""

from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, Field

from workflow_engine.core.gateway import ConnectorOutcome
from workflow_engine.core.kernel import ActionCommand


class DeliveryStatus(str, Enum):
    ACCEPTED = "accepted"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ProviderReceipt(BaseModel):
    provider_id: str
    provider_message_id: str
    status: DeliveryStatus
    occurred_at: str
    details: dict[str, Any] = Field(default_factory=dict)


class SttRequest(BaseModel):
    provider_id: str = "sandbox-stt"
    event_id: str
    call_id: str
    audio_ref: str | None = None
    transcript_hint: str | None = Field(
        default=None,
        description="Development-only transcript input; a real provider ignores this field",
    )
    locale: str = "en-US"
    is_final: bool = True
    contains_secret_dtmf: bool = False

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "provider_id": "sandbox-stt",
                    "event_id": "EV-1001",
                    "call_id": "CALL-1001",
                    "transcript_hint": "I need help with a card transaction",
                    "locale": "en-US",
                    "is_final": True,
                }
            ]
        }
    }


class SttResult(BaseModel):
    provider_id: str
    event_id: str
    call_id: str
    transcript: str
    confidence: float = Field(ge=0, le=1)
    is_final: bool
    simulated: bool
    redacted: bool = False


class TtsRequest(BaseModel):
    provider_id: str = "sandbox-tts"
    request_id: str
    call_id: str
    text: str = Field(min_length=1, max_length=10000)
    locale: str = "en-US"
    voice: str = "default"
    ssml: bool = False

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "provider_id": "sandbox-tts",
                    "request_id": "TTS-1001",
                    "call_id": "CALL-1001",
                    "text": "Please confirm the disputed amount.",
                    "locale": "en-US",
                    "voice": "default",
                }
            ]
        }
    }


class TtsResult(BaseModel):
    provider_id: str
    request_id: str
    call_id: str
    playback_id: str
    media_ref: str
    simulated: bool


class TelephonyEventType(str, Enum):
    CALL_STARTED = "call_started"
    DTMF = "dtmf"
    TRANSCRIPT = "transcript"
    PLAYBACK_COMPLETED = "playback_completed"
    BARGE_IN = "barge_in"
    TRANSFER_REQUESTED = "transfer_requested"
    DISCONNECTED = "disconnected"


class TelephonyEvent(BaseModel):
    provider_id: str
    event_id: str
    call_id: str
    event_type: TelephonyEventType
    sequence: int = Field(ge=0)
    occurred_at: str
    payload: dict[str, Any] = Field(default_factory=dict)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "provider_id": "sandbox-telephony",
                    "event_id": "TEL-1001",
                    "call_id": "CALL-1001",
                    "event_type": "call_started",
                    "sequence": 1,
                    "occurred_at": "2026-07-12T12:00:00Z",
                    "payload": {"from": "+1-555-0100"},
                }
            ]
        }
    }


class HandoffRequest(BaseModel):
    handoff_id: str
    conversation_id: str
    case_id: str
    queue: str
    priority: str = "normal"
    context: dict[str, Any]


class HandoffReceipt(BaseModel):
    provider_id: str
    handoff_id: str
    provider_ticket_id: str
    status: str
    details: dict[str, Any] = Field(default_factory=dict)


class SpeechToTextProvider(Protocol):
    provider_id: str

    async def transcribe(self, request: SttRequest) -> SttResult: ...


class TextToSpeechProvider(Protocol):
    provider_id: str

    async def synthesize(self, request: TtsRequest) -> TtsResult: ...


class TelephonyProvider(Protocol):
    provider_id: str

    async def accept_event(self, event: TelephonyEvent) -> ProviderReceipt: ...


class ChatProvider(Protocol):
    provider_id: str

    async def send(self, message: dict[str, Any]) -> ProviderReceipt: ...


class HandoffProvider(Protocol):
    provider_id: str

    async def enqueue(self, request: HandoffRequest) -> HandoffReceipt: ...
    async def status(self, provider_ticket_id: str) -> HandoffReceipt: ...


class ActionProvider(Protocol):
    provider_id: str

    async def dispatch(self, command: ActionCommand) -> ConnectorOutcome: ...
    async def reconcile(
        self, command: ActionCommand, prior: dict[str, Any] | None
    ) -> ConnectorOutcome: ...
