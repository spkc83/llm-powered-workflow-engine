"""Tests for the channel abstraction layer."""

import pytest

from workflow_engine.channels.base import (
    ChannelRegistry,
    ChannelType,
    InboundMessage,
    OutboundMessage,
)
from workflow_engine.channels.http import HttpChannel, WebSocketChannel


class TestInboundMessage:
    def test_create_with_defaults(self):
        msg = InboundMessage(
            channel=ChannelType.HTTP_REST,
            user_id="u1",
            text="Hello",
        )
        assert msg.channel == ChannelType.HTTP_REST
        assert msg.user_id == "u1"
        assert msg.text == "Hello"
        assert msg.timestamp is not None
        assert msg.attachments == []

    def test_with_metadata(self):
        msg = InboundMessage(
            channel=ChannelType.WEBSOCKET,
            user_id="u1",
            text="Hi",
            metadata={"source": "mobile"},
        )
        assert msg.metadata["source"] == "mobile"


class TestOutboundMessage:
    def test_create_with_quick_replies(self):
        msg = OutboundMessage(
            channel=ChannelType.HTTP_REST,
            user_id="u1",
            session_id="s1",
            text="Choose an option:",
            quick_replies=["Refund", "Complaint"],
        )
        assert len(msg.quick_replies) == 2


class TestHttpChannel:
    @pytest.mark.asyncio
    async def test_receive(self):
        channel = HttpChannel()
        msg = await channel.receive({
            "user_id": "CUST-456",
            "message": "I want a refund",
            "session_id": "s1",
        })
        assert isinstance(msg, InboundMessage)
        assert msg.channel == ChannelType.HTTP_REST
        assert msg.user_id == "CUST-456"
        assert msg.text == "I want a refund"

    @pytest.mark.asyncio
    async def test_format_response(self):
        channel = HttpChannel()
        msg = OutboundMessage(
            channel=ChannelType.HTTP_REST,
            user_id="u1",
            session_id="s1",
            text="Refund processed.",
        )
        response = await channel.format_response(msg)
        assert response["response"] == "Refund processed."
        assert response["session_id"] == "s1"

    @pytest.mark.asyncio
    async def test_format_response_with_quick_replies(self):
        channel = HttpChannel()
        msg = OutboundMessage(
            channel=ChannelType.HTTP_REST,
            user_id="u1",
            session_id="s1",
            text="Choose:",
            quick_replies=["Yes", "No"],
        )
        response = await channel.format_response(msg)
        assert response["quick_replies"] == ["Yes", "No"]


class TestWebSocketChannel:
    @pytest.mark.asyncio
    async def test_receive(self):
        channel = WebSocketChannel()
        msg = await channel.receive({
            "user_id": "u1",
            "message": "Hello",
        })
        assert msg.channel == ChannelType.WEBSOCKET

    @pytest.mark.asyncio
    async def test_format_response(self):
        channel = WebSocketChannel()
        msg = OutboundMessage(
            channel=ChannelType.WEBSOCKET,
            user_id="u1",
            session_id="s1",
            text="Response text",
        )
        frame = await channel.format_response(msg)
        assert frame["type"] == "agent_response"
        assert frame["text"] == "Response text"


class TestChannelRegistry:
    def test_register_and_get(self):
        reg = ChannelRegistry()
        channel = HttpChannel()
        reg.register(channel)
        assert reg.get(ChannelType.HTTP_REST) is channel

    def test_get_missing_returns_none(self):
        reg = ChannelRegistry()
        assert reg.get(ChannelType.SMS) is None

    def test_list_channels(self):
        reg = ChannelRegistry()
        reg.register(HttpChannel())
        reg.register(WebSocketChannel())
        channels = reg.list_channels()
        assert ChannelType.HTTP_REST in channels
        assert ChannelType.WEBSOCKET in channels
