# Upstream Integration Guide

This guide is the implementation contract for chat, telephony, speech-to-text
(STT), text-to-speech (TTS), action systems, and human-agent platforms. The core
engine is vendor-neutral. Built-in adapters emulate these contracts only in
`ENVIRONMENT=dev`.

Read [Application Architecture](architecture.md) for the system boundary and full
IVR/action/handoff sequences before implementing a provider.

## Safety and deployment modes

`UPSTREAM_MODE` has three values:

| Mode | Purpose | Consequential behavior |
|---|---|---|
| unset in `dev` / `sandbox` | Local development and conformance tests | SQLite emulators are enabled and every outcome says `simulated: true`. |
| unset outside `dev` / `disabled` | Fail-closed deployment | Upstream endpoints return `503`; actions do not leave the engine. |
| `provider` | Deployment-supplied real adapters | `main.py` loads and initializes a complete trusted `ProviderBundle`; startup fails if the factory is missing or invalid. |

`UPSTREAM_MODE=sandbox` is rejected when `ENVIRONMENT=production`. Never route
production traffic to the sandbox database.

### Provider bundle loading

Set `UPSTREAM_MODE=provider` and
`PROVIDER_BUNDLE_FACTORY=package.module:create_bundle`. The trusted callable receives
validated settings and returns a `ProviderBundle` containing STT, TTS, telephony,
chat, handoff, action, and authoritative-resource adapters. Startup rejects provider
mode without the factory or when the return type is invalid. Provider code must be
installed in the deployment image; factory paths are privileged code-execution
configuration and must never come from requests or tenant data.

Interactive API documentation is available at `/docs`; ReDoc is at `/redoc`.
`GET /api/v1/integrations/contracts` publishes JSON Schema for HTTP bodies and
WebSocket frames because OpenAPI itself does not describe WebSocket messages.

## Common provider rules

Every provider implementation must:

1. assign a stable `provider_id` namespace;
2. preserve the engine's message or action idempotency key across retries;
3. return authoritative `succeeded`, `failed`, or `unknown` semantics;
4. never map a transport timeout to business failure unless the provider proves no
   commit occurred;
5. redact secrets before logs, transcripts, inbox/outbox payloads, or error text;
6. validate callback authentication and replay protection outside model-visible
   state;
7. propagate correlation, causation, conversation/call, and provider event IDs;
8. implement a conformance suite using success, rejection, pre-commit timeout,
   post-commit timeout, duplicate, out-of-order, and reconnect cases.

Use an `integration` service identity for channel ingestion/delivery and provider
callbacks. It has no financial, policy-administration, or SAR permission. Ordinary
customer/staff clients are assigned server-side direct channel namespaces rather
than being trusted to invent a provider namespace.

## Chat integration

### Inbound REST

Canonical endpoint: `POST /api/v1/conversations/turns` with `channel: "chat"`.
The compatibility endpoint `POST /api/v1/chat` delegates to the same turn service.

```json
{
  "provider_id": "acme-chat",
  "message_id": "msg-000042",
  "conversation_id": "conv-1001",
  "customer_id": "CUST-456",
  "channel": "chat",
  "text": "I need help with an order",
  "sequence": 42,
  "locale": "en-US",
  "timezone": "America/Chicago",
  "consent_snapshot": {}
}
```

Deduplication is scoped to `(provider_id, message_id)`. Sequence gaps are durably
quarantined. After sending the missing message, resend the quarantined message with
the same ID; it is accepted only when it becomes the next sequence.

### WebSocket

Connect to `/api/v1/ws/chat`. When authentication is enabled, send
`Authorization: Bearer <JWT>` during the upgrade. Each inbound frame follows the
schema returned by `/api/v1/integrations/contracts`:

```json
{
  "type": "user_turn",
  "provider_id": "acme-chat",
  "message_id": "msg-000042",
  "session_id": "conv-1001",
  "user_id": "CUST-456",
  "message": "I need help with an order"
}
```

The engine deliberately buffers the complete safe response rather than streaming
unverified consequential claims. It sends `agent_response`, followed by
`stream_end`. Duplicate input produces `duplicate_suppressed`.

### Outbound and receipts

The development delivery adapter is exposed at:

- `POST /api/v1/integrations/chat/deliveries`
- `POST /api/v1/integrations/chat/receipts`
- `GET /api/v1/operations/delivery-receipts`

A real adapter implements `ChatProvider.send()` and maps provider callbacks to
`ProviderReceipt`. Receipt states are `accepted`, `delivered`, `read`, `failed`,
and `unknown`. A delivery receipt is not evidence that a customer read or consented
to content unless the provider contract explicitly proves that state.

## IVR and telephony integration

The media plane remains outside ADK. Telephony, STT, and TTS providers normalize
into these independent ports:

- `SpeechToTextProvider.transcribe()`
- `TextToSpeechProvider.synthesize()`
- `TelephonyProvider.accept_event()`

### STT

Development endpoint: `POST /api/v1/integrations/ivr/stt:transcribe`.
`transcript_hint` exists only for the stub; a real STT implementation ignores it
and consumes `audio_ref` or its provider-native media stream. Stub results always
include `simulated: true`. When `contains_secret_dtmf` is true, output is
`[REDACTED DTMF]` and confidence is zero.

STT output is always an asserted fact. Confidence alone never promotes a transcript
to verified. Interrupted or low-confidence values require deterministic readback,
secure DTMF confirmation, or authoritative-system verification.

### TTS

Development endpoint: `POST /api/v1/integrations/ivr/tts:synthesize`. The stub
returns a deterministic `sandbox://tts/...` media reference; it does not generate
or claim to generate audio. A real adapter must report playback IDs and accept
playback-completed and barge-in events.

### Telephony events

Development endpoint: `POST /api/v1/integrations/ivr/telephony/events`.
Supported normalized event types are:

- `call_started`
- `dtmf`
- `transcript`
- `playback_completed`
- `barge_in`
- `transfer_requested`
- `disconnected`

Use one monotonically increasing sequence per provider/call stream. Never include
PCI/authentication digits in `payload`; tokenize them in the telephony provider's
secure collection flow.

### Processing an IVR turn

Send the final transcript to `POST /api/v1/conversations/turns` with
`channel: "ivr"`, `asr_confidence`, interruption state, and a consent snapshot.
The response exposes `requires_readback`. NAM controls can block processing outside
development when recording or transcription consent is absent.

## Consequential action integration

The model may call a proposal-only tool, but only trusted host code creates a
durable proposal and only host confirmation invokes `ConsequentialActionService`.
Chat exposes structured proposals; clients must not parse model prose. The closed
typed catalog includes:

- refund;
- store credit;
- case status update;
- EFT dispute filing;
- provisional credit;
- supervisor escalation;
- case note;
- account restriction;
- SAR submission by secure narrative reference;
- alert closure.

`POST /api/v1/core/actions` accepts all typed payloads. `/api/v1/core/refunds`
remains a compatibility wrapper. Conversation clients normally use the proposal,
confirm/cancel, and status endpoints documented in [Action Bridge](action-bridge.md).

### Authoritative resource contract

Clients cannot label facts verified. A command references an upstream resource:

```json
"resource": {"resource_type": "order", "resource_id": "ORD-123"}
```

The configured resource adapter reloads that resource. Payload identifiers and
amounts must exactly match it before the kernel commits verified facts. The dev
sandbox seeds resources through `PUT /api/v1/dev/sandbox/resources`; that route is
not registered outside development.

### Action provider contract

An `ActionProvider` implements:

```python
async def dispatch(command: ActionCommand) -> ConnectorOutcome: ...
async def reconcile(command: ActionCommand, prior: dict | None) -> ConnectorOutcome: ...
```

`dispatch()` receives a stable idempotency key. If the provider response is
ambiguous, return `unknown`. `reconcile()` queries provider state by business key or
provider reference; it must not redispatch.

### Per-action connector registry

`ACTION_REGISTRY_PATH` binds closed actions to development SQLite, built-in
REST/OpenAPI, or trusted Python connectors. WebSocket binding models are
contract-only in v3.2 and fail startup when enabled without a custom runtime.

REST bindings require an allowed host, idempotency header, timeout, explicit
status mappings, pinned local OpenAPI digest/operation, safe response fields, and
reconciliation for asynchronous acceptance. Production requires HTTPS and rejects
inline secrets, unknown actions, and SQLite bindings. OpenAPI defines wire shape;
engine code still owns permission, policy, consent, approval, and fact authority.

A registry may intentionally bind only part of the closed catalog. The catalog API
marks unbound entries `available: false`, and proposal preparation rejects them;
there is no silent fallback to a default connector once a registry is active.

The provider bundle still supplies channel and resource adapters. The registry can
override per-action connector selection but does not replace the bundle in provider
mode. See [Action Bridge](action-bridge.md) for the complete YAML/JSON schema.

### MCP

Streamable HTTP at `/mcp` exposes proposal-only `actions_prepare` and read-only
`actions_get_status`, catalog/proposal resources, and safety/workflow prompts. It
uses the same authenticated `ActionBridge` and rejects actor, customer, policy,
evidence, idempotency, provider URL, credential, and binding fields in tool
arguments. Staff hosts bind the serviced customer with
`X-Workflow-Customer-ID`; optional procedure/conversation/message headers provide
correlation. MCP has no confirm or execution tool; confirmation remains a trusted
REST/UI host operation.

The SQLite sandbox supports `success`, `rejected`, `timeout_before_commit`, and
`timeout_after_commit` through
`PUT /api/v1/dev/sandbox/action-scenarios`. Post-commit timeout is the critical
conformance case: initial status is unknown, reconciliation finds the committed
record, and a replay returns the same provider action ID.

## Human-agent platform integration

A human-agent platform is the queue/contact-center/ticket system where staff accept
and resolve escalations. The engine does not implement a full agent desktop.

- `POST /api/v1/handoffs` creates and queues a context packet.
- `GET /api/v1/handoffs/{handoff_id}` returns authoritative engine state.
- `POST /api/v1/handoffs/{handoff_id}/callbacks` applies authenticated provider
  state changes.

Lifecycle:

```text
requested -> queued -> accepted -> connected -> resolved
                    \-> timed_out / reassigned / failed / bot_reentry
```

Queued is not accepted; accepted is not connected. The customer must not be told a
human is connected until the durable state is `connected`. Context should include
verified facts, unresolved questions, policy package, action attempts, and source
references. Generated summaries remain proposals.

## Policy integration

Policy APIs provide the simple lifecycle requested by the project:

- `POST /api/v1/policies` — draft, author is authenticated actor;
- `POST /api/v1/policies/{id}/approve` — different authenticated actor;
- `POST /api/v1/policies/{id}/activate`;
- `POST /api/v1/policies/{id}/retire`;
- `GET /api/v1/policies`.

Signatures include `signing_key_id`. Key material remains outside the repository.
During rotation, configure old IDs in `POLICY_VERIFICATION_KEYS` until every
retained package/action has passed its verification and retention window; old keys
verify history but never sign new states.
Only one package per procedure/jurisdiction is active in the SQLite adapter.
Additional databases implement `PolicyRepository` and register by URL scheme.
The reference app accepts trusted dotted factories through
`CORE_STORE_ADAPTER_FACTORY` and `POLICY_REPOSITORY_ADAPTER_FACTORY`.

## Operational verification

Before enabling a provider:

1. Run its conformance suite against the adapter port.
2. Verify duplicate and sequence-gap behavior.
3. Exercise post-commit timeout and reconciliation.
4. Verify `/api/v1/operations/outbox`, `/actions`, `/delivery-receipts`, and
   `/conversation-quarantine`.
5. Verify `/api/v1/operations/audit-integrity` reports a valid chain.
6. Test provider credential rotation, callback replay rejection, data redaction,
   failover, and rollback.
7. Obtain legal approval for the configured NAM profile and retention settings.
