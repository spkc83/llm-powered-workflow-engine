"""Trusted action bridge surfaces used by conversation and API adapters."""

from .bridge import ActionBridge, ActionConfirmationContext, ActionIntent, TrustedActionContext

__all__ = [
    "ActionBridge",
    "ActionConfirmationContext",
    "ActionIntent",
    "TrustedActionContext",
]
