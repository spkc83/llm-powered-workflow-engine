# API Reference

FastAPI serves OpenAPI at `/openapi.json`, Swagger UI at `/docs`, and ReDoc at
`/redoc`. All current routes use `/api/v1`; hidden `/api/...` routes preserve
legacy client compatibility.

For complete payload schemas and live examples, use Swagger. WebSocket frame JSON
Schemas are available from `GET /api/v1/integrations/contracts` because WebSocket
frames are outside OpenAPI.

## Authentication, identity, and errors

When authentication is enabled, send `Authorization: Bearer <JWT>`. The token binds
the actor identity and role; `customer_id` is the serviced customer and cannot be
used to impersonate another customer. Integration tokens require channel-ingest,
delivery, or callback permissions. Actions also require their specific permission;
policy and operations routes require administrative read/write permissions.

| Status | Meaning |
|---|---|
| 400/422 | Invalid payload or unsupported typed action. |
| 401 | Missing, expired, or invalid bearer token. |
| 403 | Actor lacks permission or customer delegation. |
| 404 | Requested case/action/handoff/policy/resource does not exist. |
| 409 | Version, lifecycle, idempotency, sequence, or jurisdiction conflict. |
| 429 | Rate limit exceeded. |
| 503 | Required upstream capability is disabled or unavailable. |

Reuse an idempotency key only for the same action, customer, and parameters. A key
reused for a different command is rejected as a conflict.

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

Chat responses retain `response` and `session_id` and now include
`action_proposals`. Clients must use this structured list rather than parsing
assistant text to discover actions.

## Conversational action bridge

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/actions/catalog` | Closed action catalog, requirements, permission, and active binding visible to the actor. |
| POST | `/api/v1/action-proposals` | Prepare a validated pending proposal; performs no provider effect. |
| GET | `/api/v1/action-proposals` | List proposals created by the actor, optionally by `conversation_id`. |
| GET | `/api/v1/action-proposals/{proposal_id}` | Read one actor/customer-bound proposal and apply lazy expiry. |
| POST | `/api/v1/action-proposals/{proposal_id}/confirm` | Capture server-owned host evidence and submit through the typed gateway. |
| POST | `/api/v1/action-proposals/{proposal_id}/cancel` | Cancel a pending proposal without execution. |
| GET | `/api/v1/actions/{action_id}` | Actor/customer-bound authoritative action, outcome, and event history. |

Catalog entries include `available`. With a declarative registry, an action that
has no enabled binding remains visible for discovery but has `available: false`
and `binding: null`; proposal preparation for it fails closed. Confirm responses
keep the proposal `action` name and return the typed effect record separately as
`action_record`.

Proposal creation accepts an action intent, arguments, optional authoritative
resource reference, and conversation/message correlation. It does not accept
actor identity, policy ID, evidence, idempotency key, connector binding, endpoint,
or credential; those are server-derived.

Proposal status is `pending`, `confirmed`, `cancelled`, or `expired`. `confirmed`
means an action record was created, not that the provider succeeded. Inspect the
linked action status. Confirmation/cancellation replays are idempotent when they
match the stored lifecycle; cross-actor/customer access and conflicting transitions
are rejected.

## Direct typed action and operations APIs

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/core/refunds` | Specialized refund vertical slice with authoritative order reload. |
| POST | `/api/v1/core/actions` | Discriminated typed command for every consequential action, including refund. |
| GET | `/api/v1/operations/actions` | Inspect durable action lifecycle/outcome records. |
| GET | `/api/v1/operations/actions/{id}/events` | Read append-oriented requested/authorized/dispatched/outcome evidence. |
| POST | `/api/v1/operations/workers/actions:run` | Lease and process due action outbox entries. |
| POST | `/api/v1/operations/workers/reconciliation:run` | Reconcile unknown outcomes without redispatch. |

Action lifecycle is `authorized -> dispatched -> succeeded|failed|unknown`, with
`unknown -> reconciled|failed|unknown`. Only `succeeded` and `reconciled` support a
customer-visible success claim.

Direct typed endpoints are for trusted service clients. Customer conversation UIs
should use proposal/confirmation so the user reviews an authoritative preview.

## MCP action façade

`/mcp` is a FastMCP Streamable HTTP mount protected by the same outer application
authentication middleware. It is not represented as ordinary OpenAPI operations;
its location/capabilities are also reported by `/api/v1/integrations/contracts`.

Exposed model surfaces:

- tools: `actions_prepare`, `actions_get_status`;
- resource: `actions://catalog`;
- template: `actions://proposals/{proposal_id}`;
- prompts: `actions_workflow`, `actions_safety`.

There is deliberately no confirm, approve, execute, dispatch, connector, provider,
or credential tool. Staff hosts must send `X-Workflow-Customer-ID`; optional
procedure, conversation, and message headers bind trusted context. Customer tokens
are bound to their own identity. Tool arguments cannot override trusted context.

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
- `/ready` (database/policy/provider readiness)
- `/api/v1/procedures` and `/procedures/active`
- `/api/v1/session/{session_id}/state` and `/procedure`
- `/api/v1/customers`, `/sessions`, and allow-listed `/tables/{table_name}`

Administrative and consequential routes require their documented RBAC permission
when authentication is enabled. Actor and serviced customer are different
identities; staff delegation requires customer-read permission.
