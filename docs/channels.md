# Chat and IVR Channel Contract

## Shared envelope

Chat and IVR use a provider message ID, conversation ID, customer ID, locale,
timezone, correlation/causation IDs, consent snapshot, sequence, and capability
metadata. The durable inbox owns deduplication.

## Chat

REST and WebSocket use the same authenticated actor/customer binding. WebSocket
production handshakes require a Bearer token. Informational text may stream;
consequential promises, regulated disclosures, and success claims wait for an
authoritative verdict.

## IVR

The provider adapter supplies final transcript, confidence, interruption state,
and provider message ID. The media plane is intentionally outside ADK graph
workflows. Required production adapter behaviors:

- recording/transcription consent before capture;
- DTMF and PCI-secret redaction;
- confidence thresholds and number readback;
- barge-in/cancellation propagation;
- captions/TTY and accessible alternate path;
- delivery/failure callbacks and reconnect identity checks;
- jurisdiction fixtures for United States, Canada, and configured territories.

## Ordering and retries

Stable duplicate IDs are suppressed. Provider sequence gaps must be quarantined or
resolved before consequential processing. A retry reuses the same message ID and
action idempotency key.
