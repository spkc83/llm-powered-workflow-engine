"""Trusted deployment loading for a complete upstream provider bundle."""

from __future__ import annotations

from dataclasses import dataclass
import inspect
from typing import Any

from workflow_engine.core.gateway import ActionConnector
from workflow_engine.core.adapter_loading import load_factory
from workflow_engine.settings import Settings

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


def load_action_connector_registry(
    settings: Settings,
    *,
    sqlite_connectors: dict[str, ActionConnector] | None = None,
):
    """Load the optional declarative action registry without changing ProviderBundle."""
    if settings.action_registry_path is None:
        return None
    from .registry import ActionConnectorRegistry, load_registry_config

    secret_provider = None
    if settings.action_secret_provider_factory:
        secret_provider = load_factory(settings.action_secret_provider_factory)(settings)

    return ActionConnectorRegistry(
        load_registry_config(settings.action_registry_path),
        environment=settings.environment,
        sqlite_connectors=sqlite_connectors,
        secret_provider=secret_provider,
    )
