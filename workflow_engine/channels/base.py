"""Channel abstraction base classes and models.

Defines the unified message format and channel interface that all
channel adapters must implement.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ChannelType(str, Enum):
    """Supported communication channels."""
    HTTP_REST = "http_rest"
    WEBSOCKET = "websocket"
    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    VOICE_IVR = "voice_ivr"
    MOBILE_APP = "mobile_app"
    SLACK = "slack"
    TEAMS = "teams"


class MessageAttachment(BaseModel):
    """File or media attachment on a message."""
    filename: str
    content_type: str
    url: Optional[str] = None
    size_bytes: Optional[int] = None
    data: Optional[bytes] = None


class InboundMessage(BaseModel):
    """Normalized inbound message from any channel.

    All channel adapters convert their native message format into this
    unified representation before passing to the workflow engine.
    """
    channel: ChannelType
    channel_message_id: Optional[str] = None
    user_id: str
    session_id: Optional[str] = None
    text: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    attachments: list[MessageAttachment] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Channel-specific context
    reply_to_message_id: Optional[str] = None
    language: Optional[str] = None


class OutboundMessage(BaseModel):
    """Normalized outbound message to be formatted by channel adapters.

    The workflow engine produces this unified format. Each channel adapter
    converts it to the native format for delivery.
    """
    channel: ChannelType
    user_id: str
    session_id: str
    text: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    attachments: list[MessageAttachment] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Structured content for rich channels
    quick_replies: list[str] = Field(default_factory=list)
    cards: list[dict] = Field(default_factory=list)


class Channel(ABC):
    """Abstract base class for channel adapters.

    Each channel adapter handles protocol-specific details for receiving
    and sending messages via a particular communication channel.
    """

    @property
    @abstractmethod
    def channel_type(self) -> ChannelType:
        """The type of channel this adapter handles."""
        ...

    @abstractmethod
    async def receive(self, raw_data: Any) -> InboundMessage:
        """Convert a raw channel-specific message into a normalized InboundMessage.

        Args:
            raw_data: The raw message data from the channel (request body, webhook payload, etc.).

        Returns:
            Normalized InboundMessage.
        """
        ...

    @abstractmethod
    async def send(self, message: OutboundMessage) -> dict:
        """Send a normalized OutboundMessage via the channel.

        Args:
            message: The normalized outbound message.

        Returns:
            Delivery metadata (message ID, status, etc.).
        """
        ...

    @abstractmethod
    async def format_response(self, message: OutboundMessage) -> Any:
        """Format an OutboundMessage into the channel's native response format.

        Args:
            message: The normalized outbound message.

        Returns:
            Channel-specific formatted response.
        """
        ...


class ChannelRegistry:
    """Registry for channel adapters.

    Allows the engine to route messages to/from the appropriate channel
    adapter based on the channel type.
    """

    def __init__(self):
        self._channels: dict[ChannelType, Channel] = {}

    def register(self, channel: Channel) -> None:
        """Register a channel adapter."""
        self._channels[channel.channel_type] = channel

    def get(self, channel_type: ChannelType) -> Optional[Channel]:
        """Get a channel adapter by type."""
        return self._channels.get(channel_type)

    def list_channels(self) -> list[ChannelType]:
        """List all registered channel types."""
        return list(self._channels.keys())
