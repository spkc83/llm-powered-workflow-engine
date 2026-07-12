# v3 Trust and Threat Model

## Safety claim

Model, prompt, tool arguments, channel payloads, ADK state, and generated summaries
are attacker-influenced proposals. They cannot independently authorize a
consequential effect. The deterministic kernel requires authenticated actor/customer
binding, permission, active signed policy, authoritative fact provenance,
consent/approval, stable idempotency, and connector outcome evidence.

## Trusted boundaries

- JWT validation/RBAC and serviced-customer delegation;
- deterministic core and signed active policy registry;
- conforming `CoreStore`/`PolicyRepository` transaction semantics;
- authenticated upstream adapters and their authoritative resource reloads;
- secret manager, signing keys, provider credentials, and approved operators.

ADK sessions, model callbacks, transcripts, attachments, provider webhooks, sandbox
payloads, and mutable client fields are not trusted.

## Threats and controls

| Threat | v3 control |
|---|---|
| Prompt injection invokes a write | Consequential model tools remain frozen; typed action service/gateway is independent. |
| Client calls action with invented amount | Authoritative resource adapter reload and exact fact/parameter match. |
| Duplicate/resumed provider effect | Unique business idempotency, atomic action/outbox insertion, provider key reuse. |
| Timeout after provider commit | `unknown` state and query-only reconciliation; never blind redispatch. |
| Two workers dispatch once | Atomic action claim and leased outbox. |
| Provider message-ID collision | Composite `(provider_id,message_id)` identity. |
| Out-of-order channel state | Durable sequence gap quarantine before ADK/action processing. |
| REST/WS safety drift | One `ConversationService`; WS buffers full safety verdict. |
| Low-confidence speech authorizes action | ASR stays asserted and requires readback/authoritative promotion. |
| Secret DTMF/transcript leakage | Secure collection requirement and stub redaction; adapters must redact before logs/storage. |
| False human connection | Validated requested/queued/accepted/connected lifecycle. |
| Policy tampering or restart loss | Durable canonical signed packages, key ID, one active version constraint. |
| Sandbox in production | Production settings reject sandbox; disabled adapters return `503`. |
| Audit modification | Append-order hash-chain verification plus required immutable backup/external anchoring. |
| Cross-customer session | Actor/customer composite ownership and delegation permission checks. |
| Client spoofs provider namespace | Only admin/integration identities retain supplied provider IDs; direct clients receive a server namespace. |

## Residual risks

- The built-in NAM profile is not legal advice and requires sub-jurisdiction review.
- A local hash chain cannot prove that a tail was deleted without external anchoring.
- Provider truth is only as strong as callback authentication, query semantics, and
  conformance testing.
- SQLite is the reference adapter; multi-instance production stores need their own
  concurrency conformance evidence.
- Legacy dev action functions remain non-production surfaces; production model
  exposure stays frozen.

## Production gate

Do not enable a provider/action until callback authentication, redaction, duplicate,
ordering, pre/post-commit timeout, reconciliation, outage, recovery, and rollback
cases pass. Require zero unauthorized actions in the versioned adversarial corpus
and explicit owner acceptance of jurisdiction, retention, queue, and error budgets.
