# Core Engine Architecture

This page defines the control-plane invariants. Read
[Application Architecture](architecture.md) first for system context, runtime
topology, data ownership, trust boundaries, and complete chat/IVR/action/handoff
flows.

## Runtime topology

```text
Shiny/dev client ──HTTP/WS──▶ FastAPI API process
                                  │ transactions
                         Core/Policy/Reference DB
                                  │ durable lease
                         Worker process
                         dispatch + reconciliation
                                  │ typed ports
                         sandbox or ProviderBundle
```

ADK session storage is separate because model/session state is not authoritative.
The reference application is a modular monolith with an independently supervised
worker, not a distributed workflow platform.

## Control-plane decision

v3 remains a modular monolith with explicit ports. ADK 2.4 proposes intent, facts,
and response text. It does not authorize or dispatch business actions. The core
owns deterministic cases, fact authority, signed policy, conversation ordering,
action lifecycle, delivery, reconciliation, and handoff truth.

```text
REST / WebSocket / telephony adapters
                |
       ConversationService
  identity + NAM + inbox + safety
                |
      ADK proposal/wording layer
                |
     durable ActionBridge proposal
                |
       trusted host confirmation
                |
 case/fact kernel + active signed policy
                |
       typed ActionGateway
                |
 provider connector / sandbox / disabled
```

## Consequential actions

Every supported action has a closed `ActionSpecification`, discriminated request
payload, permission, required parameters, authoritative fact references, and
consent/approval requirement. Unknown actions and missing/stale/mismatched evidence
fail closed.

Consequential model tools are proposal-only in every environment. Trusted code
creates a pending proposal; host confirmation revalidates ownership, expiry,
resource and connector versions, consent/approval, and policy before the typed
service runs. The registry stamps immutable binding/contract versions. REST and
Python bindings execute; WebSocket bindings are validation-only in v3.2.

## Durable execution

Authorizing an action and inserting its `action.dispatch` outbox record occur in
one SQLite transaction. Workers use short compare-and-set leases compatible with
SQLite; other `CoreStore` adapters can use native locking while preserving the
contract. Provider ambiguity becomes `unknown`; the reconciliation worker queries
provider state using the same idempotency key and never redispatches to discover an
outcome. A stale `dispatched` record is treated as an interrupted/ambiguous attempt
after the configured delay and enters that same query-only reconciliation path.

## Policy

## End-to-end action sequence

```text
conversation/model → bridge: untrusted intent
bridge → core store: pending proposal + authoritative preview
host → bridge: authenticated confirmation
bridge → action service: server-derived typed command + idempotency key
action service → authoritative adapter: reload current resource/version
action service → policy/core: verify permission, facts, consent and active signature
action service → provider: synchronous first dispatch with stable idempotency key
core → database: persist succeeded, failed, or unknown
worker → core: lease outbox and recover only still-authorized actions
worker → provider: dispatch if the request path stopped before dispatch
reconciler → provider: query ambiguous outcome without redispatch
```

If dispatch may have committed but no response is known, state becomes `unknown`.
Only succeeded or reconciled evidence supports a customer-visible success claim.

Policy is durable and independent of ADK sessions. Lifecycle is
`draft -> approved -> active -> retired`; author and approver differ. Approved and
active canonical payloads are HMAC-SHA256 signed and carry `signing_key_id`. The
SQLite repository enforces one active package per procedure/jurisdiction.
Authorized actions store the policy activation signature. If that version is later
retired, delayed outbox work remains verifiable against signed policy history after
a restart; retirement does not silently invalidate already-authorized work.
Authorization resolves current policy from the durable repository rather than
trusting a process-local cache, so multiple API workers observe activation changes.

## Conversation and handoff invariants

Authentication and customer delegation run before the message enters the inbox.
The inbox deduplicates `(provider_id, message_id)` and quarantines sequence gaps.
Duplicate or quarantined turns do not reach ADK or action logic.

Handoff state is `requested → queued → accepted → connected → resolved`. Provider
acknowledgment means queued, not connected. Compare-and-set transitions prevent two
human agents from accepting the same handoff.

1. Dedupe key includes provider namespace.
2. Sequence gaps are quarantined before model or action processing.
3. REST, WebSocket, and IVR use one response-safety pipeline.
4. ASR remains asserted; low-confidence/interrupted input requires readback.
5. Queue, acceptance, connection, and resolution are different handoff states.
   Compare-and-set transitions prevent two agents from accepting the same handoff.
6. Consequential success claims require authoritative `succeeded` or `reconciled`.

## Persistence ports

`CoreStore` and `PolicyRepository` are vendor-neutral protocols. URL-scheme
factories select SQLite by default and accept deployment adapters for other
systems. A conforming adapter must preserve optimistic case versioning, unique
idempotency, atomic action/outbox insertion, leases, provider-scoped inbox
uniqueness, ordering quarantine, and policy activation uniqueness.

## Audit and observability

Audit records form an append-order SHA-256 chain. This detects modification or
middle-record deletion in the local chain; it is not a substitute for access
control, external anchoring, immutable backup, or retention governance. Operational
APIs expose action/outbox states, quarantine, receipts, reconciliation, active
policies, adapter mode, and audit-chain verification.

The metrics endpoint is an authenticated JSON snapshot, not Prometheus exposition.
Prometheus, OpenTelemetry, dashboards, alert routing, external audit anchoring, and
immutable retention are deployment responsibilities in v3.2.0.
