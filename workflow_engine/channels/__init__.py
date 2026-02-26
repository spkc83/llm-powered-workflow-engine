"""Omni-channel abstraction layer.

Provides a unified interface for handling messages across different
communication channels (web chat, WebSocket, email, SMS, etc.).
"""

from .base import (
    Channel,
    ChannelType,
    InboundMessage,
    OutboundMessage,
    MessageAttachment,
    ChannelRegistry,
)

__all__ = [
    "Channel",
    "ChannelType",
    "InboundMessage",
    "OutboundMessage",
    "MessageAttachment",
    "ChannelRegistry",
]
