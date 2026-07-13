"""Trusted deployment loading for a complete upstream provider bundle."""

from __future__ import annotations

from dataclasses import dataclass
import inspect
from typing import Any

from workflow_engine.core.gateway import ActionConnector

from .contracts import ChatProvider, HandoffProvider, SpeechToTextProvider, TelephonyProvider, TextToSpeechProvider


@dataclass(frozen=True)
class ProviderBundle:
    stt: SpeechToTextProvider
    tts: TextToSpeechProvider
    telephony: TelephonyProvider
    chat: ChatProvider
    handoff: HandoffProvider
    action: ActionConnector
    resources: Any

    async def initialize(self) -> None:
        adapters = {id(item): item for item in (
            self.stt, self.tts, self.telephony, self.chat,
            self.handoff, self.action, self.resources,
        )}
        for adapter in adapters.values():
            initialize = getattr(adapter, "initialize", None)
            if initialize is not None:
                result = initialize()
                if inspect.isawaitable(result):
                    await result


def validate_provider_bundle(value: Any) -> ProviderBundle:
    if not isinstance(value, ProviderBundle):
        raise TypeError("Provider factory must return ProviderBundle")
    return value
