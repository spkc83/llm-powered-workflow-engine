# API Reference

FastAPI serves OpenAPI at `/openapi.json`, Swagger UI at `/docs`, and ReDoc at
`/redoc`. All current routes use `/api/v1`; hidden `/api/...` routes preserve
legacy client compatibility.

For complete payload schemas and live examples, use Swagger. WebSocket frame JSON
Schemas are available from `GET /api/v1/integrations/contracts` because WebSocket
frames are outside OpenAPI.

## Conversation APIs

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/conversations/turns` | Canonical chat/IVR turn pipeline: identity, jurisdiction, dedupe/order, ADK, guardrails, response contract. |
| POST | `/api/v1/chat` | Compatibility chat request delegated to the shared pipeline. |
| POST | `/api/v1/ivr/turns` | Transcript-normalization/dedupe compatibility endpoint. |
| WS | `/api/v1/ws/chat` | Shared safe-turn pipeline over WebSocket; bearer handshake in authenticated environments. |
| GET | `/api/v1/integrations/contracts` | Machine-readable HTTP and WebSocket schemas. |

A canonical IVR request includes `provider_id`, stable `message_id`, call as
`conversation_id`, customer, transcript, confidence, interruption state, and
recording/transcription consent snapshot. Responses expose acceptance,
quarantine/duplicate state, risk, streaming permission, success-claim permission,
and readback requirements.

## Action APIs

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/core/refunds` | Specialized refund vertical slice with authoritative order reload. |
| POST | `/api/v1/core/actions` | Discriminated typed command for every other consequential action. |
| GET | `/api/v1/operations/actions` | Inspect durable action lifecycle/outcome records. |
| GET | `/api/v1/operations/actions/{id}/events` | Read append-oriented requested/authorized/dispatched/outcome evidence. |
| POST | `/api/v1/operations/workers/actions:run` | Lease and process due action outbox entries. |
| POST | `/api/v1/operations/workers/reconciliation:run` | Reconcile unknown outcomes without redispatch. |

Action lifecycle is `authorized -> dispatched -> succeeded|failed|unknown`, with
`unknown -> reconciled|failed|unknown`. Only `succeeded` and `reconciled` support a
customer-visible success claim.

## Provider adapter APIs

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/integrations/ivr/stt:transcribe` | STT adapter contract/dev stub. |
| POST | `/api/v1/integrations/ivr/tts:synthesize` | TTS adapter contract/dev stub. |
| POST | `/api/v1/integrations/ivr/telephony/events` | Normalized call lifecycle events. |
| POST | `/api/v1/integrations/chat/deliveries` | Chat outbound adapter/dev delivery. |
| POST | `/api/v1/integrations/chat/receipts` | Authenticated provider receipt callback. |

The built-in implementations are enabled only in development sandbox mode and
mark outputs `simulated: true`. See [Upstream Integration Guide](integration-guide.md).

## Human handoff

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/handoffs` | Create and enqueue context with a human-agent platform. |
| GET | `/api/v1/handoffs/{handoff_id}` | Read durable handoff state. |
| POST | `/api/v1/handoffs/{handoff_id}/callbacks` | Apply authenticated platform status change. |

## Policy and jurisdiction

| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/api/v1/policies` | List packages or create a draft. |
| POST | `/api/v1/policies/{id}/approve` | Different actor approves and signs. |
| POST | `/api/v1/policies/{id}/activate` | Atomically replace active procedure/jurisdiction package. |
| POST | `/api/v1/policies/{id}/retire` | Retire an active package. |
| GET | `/api/v1/jurisdictions/current` | Active NAM operational controls and enforcement mode. |

## Development sandbox

Registered only when `ENVIRONMENT=dev`:

| Method | Path | Purpose |
|---|---|---|
| PUT | `/api/v1/dev/sandbox/resources` | Seed a versioned authoritative upstream resource. |
| PUT | `/api/v1/dev/sandbox/action-scenarios` | Select deterministic provider outcome/failure mode. |

Production explicitly rejects `UPSTREAM_MODE=sandbox`.

## Operations and existing resources

- `/api/v1/operations/outbox`
- `/api/v1/operations/conversation-quarantine`
- `/api/v1/operations/delivery-receipts`
- `/api/v1/operations/audit-integrity`
- `/api/v1/metrics`
- `/health`
- `/api/v1/procedures` and `/procedures/active`
- `/api/v1/session/{session_id}/state` and `/procedure`
- `/api/v1/customers`, `/sessions`, and allow-listed `/tables/{table_name}`

Administrative and consequential routes require their documented RBAC permission
when authentication is enabled. Actor and serviced customer are different
identities; staff delegation requires customer-read permission.
