"""Configurable operational controls for NAM channel consent and retention.

These profiles are engineering controls, not legal conclusions. Deployments must
replace/approve them with counsel-reviewed jurisdiction fixtures.
"""

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from workflow_engine.conversation.runtime import ChannelKind


class JurisdictionProfile(BaseModel):
    profile_id: str
    regions: list[str]
    recording_consent_required: bool = True
    transcription_consent_required: bool = True
    transcript_retention_days: int = Field(default=30, ge=0)
    quiet_hours_start: int = Field(default=21, ge=0, le=23)
    quiet_hours_end: int = Field(default=8, ge=0, le=23)
    max_outbound_contacts_7d: int = Field(default=3, ge=0)
    secure_dtmf_required: bool = True
    disclaimer: str = (
        "Operational default only; obtain legal approval before production activation."
    )


class JurisdictionDecision(BaseModel):
    allowed: bool
    enforced: bool
    blocks: list[str]
    warnings: list[str]
    profile_id: str


DEFAULT_NAM_PROFILE = JurisdictionProfile(
    profile_id="NAM",
    regions=["US", "CA", "MX"],
)


def load_jurisdiction_profile(
    profile_id: str, config_path: str | Path | None = None
) -> JurisdictionProfile:
    if config_path is None:
        if profile_id != "NAM":
            raise ValueError(f"No built-in jurisdiction profile: {profile_id}")
        return DEFAULT_NAM_PROFILE
    path = Path(config_path)
    raw: dict[str, Any]
    if path.suffix.lower() == ".json":
        raw = json.loads(path.read_text())
    else:
        raw = yaml.safe_load(path.read_text())
    profiles = raw.get("profiles", raw)
    if profile_id not in profiles:
        raise ValueError(f"Jurisdiction profile not found: {profile_id}")
    return JurisdictionProfile.model_validate(
        {"profile_id": profile_id, **profiles[profile_id]}
    )


class JurisdictionGuard:
    def __init__(self, profile: JurisdictionProfile, *, enforce: bool):
        self.profile = profile
        self.enforce = enforce

    def evaluate_inbound(
        self,
        *,
        channel: ChannelKind,
        consent_snapshot: dict[str, Any],
        contains_dtmf_secret: bool = False,
        secure_dtmf_capture: bool = False,
    ) -> JurisdictionDecision:
        findings: list[str] = []
        if channel is ChannelKind.IVR:
            if self.profile.recording_consent_required and not consent_snapshot.get(
                "recording"
            ):
                findings.append("recording_consent_missing")
            if self.profile.transcription_consent_required and not consent_snapshot.get(
                "transcription"
            ):
                findings.append("transcription_consent_missing")
            if (
                contains_dtmf_secret
                and self.profile.secure_dtmf_required
                and not secure_dtmf_capture
            ):
                findings.append("secure_dtmf_capture_required")
        return JurisdictionDecision(
            allowed=not findings or not self.enforce,
            enforced=self.enforce,
            blocks=findings if self.enforce else [],
            warnings=[] if self.enforce else findings,
            profile_id=self.profile.profile_id,
        )
