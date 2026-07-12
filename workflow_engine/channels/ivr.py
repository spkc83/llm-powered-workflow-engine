"""Provider-neutral IVR normalization contract."""

from pydantic import BaseModel, Field

from workflow_engine.core.kernel import FactAuthority


class IvrTurn(BaseModel):
    provider_message_id: str
    conversation_id: str
    customer_id: str
    transcript: str
    asr_confidence: float = Field(ge=0, le=1)
    interrupted: bool
    proposed_authority: FactAuthority
    requires_readback: bool


class IvrAdapter:
    def __init__(self, min_verification_confidence: float = 0.9):
        self.min_verification_confidence = min_verification_confidence

    def normalize(
        self,
        *,
        provider_message_id: str,
        conversation_id: str,
        customer_id: str,
        transcript: str,
        asr_confidence: float,
        interrupted: bool,
    ) -> IvrTurn:
        requires_readback = interrupted or asr_confidence < self.min_verification_confidence
        # ASR output is never verified by itself. A deterministic readback/DTMF or
        # authoritative-system lookup must promote it later.
        return IvrTurn(
            provider_message_id=provider_message_id,
            conversation_id=conversation_id,
            customer_id=customer_id,
            transcript=transcript,
            asr_confidence=asr_confidence,
            interrupted=interrupted,
            proposed_authority=FactAuthority.ASSERTED,
            requires_readback=requires_readback,
        )
