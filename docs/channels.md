# Chat and IVR Channels

## One turn pipeline

REST chat, WebSocket chat, and canonical IVR turns normalize to
`MessageEnvelope` and call `ConversationService.process_turn()`. The shared path
owns provider-scoped deduplication, sequence quarantine, actor/customer context,
ADK generation, full response steering, and risk-based response contracts.

## Envelope

Every provider supplies:

- `provider_id` and stable `message_id`;
- conversation/call ID and optional sequence;
- authenticated serviced customer;
- channel, locale, timezone, and consent snapshot;
- text/final transcript and channel capabilities.

Dedupe uses `(provider_id, message_id)`, so identical IDs from different providers
do not collide. Out-of-order messages are quarantined. Providers resend the same
message after filling the sequence gap.

## Chat

`POST /api/v1/conversations/turns` is canonical. `/api/v1/chat` remains compatible.
`/api/v1/ws/chat` uses the same complete safety pass and therefore buffers
consequential/regulated responses instead of leaking unsafe token chunks.

When authentication is enabled, WebSocket upgrade requires a bearer token. Session
ownership binds actor and customer; a session cannot cross that boundary.

## IVR

Telephony, STT, and TTS are ports. The development stubs do not process real audio:
STT accepts a transcript hint and TTS returns `sandbox://` media. Real providers
implement the interfaces in `workflow_engine.integrations.contracts`.

ASR output is asserted, never verified. Low confidence or interruption requires
readback. Secret DTMF is redacted before transcript/log storage. The canonical IVR
turn includes recording and transcription consent. NAM controls are observe-only
by default in development and enforced elsewhere.

Supported normalized telephony events include call start, DTMF, transcript,
playback completion, barge-in, transfer request, and disconnect.

## Human assistance

The engine owns truthful state while a human-agent adapter owns its vendor ticket:

`requested -> queued -> accepted -> connected -> resolved`

Timeout, rejection, reassignment, failure, and bot re-entry are explicit. Queue
acknowledgement never becomes a false “connected” claim.

See [Upstream Integration Guide](integration-guide.md) for payloads, callbacks,
conformance cases, and operational enablement.
