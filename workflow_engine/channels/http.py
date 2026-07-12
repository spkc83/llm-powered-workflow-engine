"""HTTP REST channel adapter.

Handles the standard HTTP request/response chat interface — this is the
existing `/api/chat` endpoint adapted to the channel abstraction.
"""

from typing import Any

from .base import Channel, ChannelType, InboundMessage, OutboundMessage


class HttpChannel(Channel):
    """HTTP REST API channel adapter."""

    @property
    def channel_type(self) -> ChannelType:
        return ChannelType.HTTP_REST

    async def receive(self, raw_data: Any) -> InboundMessage:
        """Convert an HTTP chat request body into an InboundMessage.

        Args:
            raw_data: Dict with 'message', 'user_id', and optional 'session_id'.
        """
        return InboundMessage(
            channel=ChannelType.HTTP_REST,
            channel_message_id=raw_data.get("message_id"),
            user_id=raw_data["user_id"],
            session_id=raw_data.get("session_id"),
            text=raw_data["message"],
            metadata=raw_data.get("metadata", {}),
        )

    async def send(self, message: OutboundMessage) -> dict:
        """For HTTP, sending is handled by the response — this is a no-op.

        The HTTP response is returned synchronously via format_response().
        """
        return {"status": "delivered", "channel": self.channel_type.value}

    async def format_response(self, message: OutboundMessage) -> dict:
        """Format the outbound message as an HTTP JSON response body."""
        response = {
            "response": message.text,
            "session_id": message.session_id,
        }
        if message.quick_replies:
            response["quick_replies"] = message.quick_replies
        if message.cards:
            response["cards"] = message.cards
        if message.metadata:
            response["metadata"] = message.metadata
        return response


class WebSocketChannel(Channel):
    """WebSocket channel adapter for real-time streaming responses."""

    @property
    def channel_type(self) -> ChannelType:
        return ChannelType.WEBSOCKET

    async def receive(self, raw_data: Any) -> InboundMessage:
        """Convert a WebSocket message into an InboundMessage.

        Args:
            raw_data: JSON-parsed WebSocket message dict.
        """
        return InboundMessage(
            channel=ChannelType.WEBSOCKET,
            channel_message_id=raw_data.get("message_id"),
            user_id=raw_data["user_id"],
            session_id=raw_data.get("session_id"),
            text=raw_data["message"],
            metadata=raw_data.get("metadata", {}),
        )

    async def send(self, message: OutboundMessage) -> dict:
        """Send via WebSocket connection.

        Note: Actual WebSocket send is handled by the endpoint, not here.
        This formats the message for the WebSocket protocol.
        """
        return await self.format_response(message)

    async def format_response(self, message: OutboundMessage) -> dict:
        """Format as a WebSocket JSON frame."""
        return {
            "type": "agent_response",
            "text": message.text,
            "session_id": message.session_id,
            "timestamp": message.timestamp,
            "quick_replies": message.quick_replies,
            "cards": message.cards,
            "metadata": message.metadata,
        }
