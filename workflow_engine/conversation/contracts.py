"""Customer-visible response controls shared by chat and IVR."""

from enum import Enum

from pydantic import BaseModel

from workflow_engine.conversation.runtime import ChannelKind


class RiskLevel(str, Enum):
    INFORMATIONAL = "informational"
    CONSEQUENTIAL = "consequential"
    REGULATED = "regulated"


class ResponseDecision(BaseModel):
    may_stream: bool
    may_claim_success: bool
    requires_approved_content: bool
    requires_readback: bool


class ResponseContract:
    def evaluate(
        self,
        *,
        channel: ChannelKind,
        risk: RiskLevel,
        authoritative_status: str | None,
    ) -> ResponseDecision:
        consequential = risk in {RiskLevel.CONSEQUENTIAL, RiskLevel.REGULATED}
        succeeded = authoritative_status in {"succeeded", "reconciled"}
        return ResponseDecision(
            may_stream=not consequential,
            may_claim_success=succeeded,
            requires_approved_content=risk is RiskLevel.REGULATED,
            requires_readback=channel is ChannelKind.IVR and consequential,
        )
