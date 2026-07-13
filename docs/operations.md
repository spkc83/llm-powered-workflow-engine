# Operations Runbook

This describes the controls packaged in v3.2.0. Compose is a reference single-host
topology, not a complete production platform. Providers, TLS/ingress, secret
management, approved storage, backups, monitoring, and incident tooling remain
deployment responsibilities.

## Startup gate

1. Load environment and secret-manager values.
2. Initialize/migrate domain/core and policy stores.
3. Initialize the separate ADK 2.4 session store.
4. Verify active policy signatures and distinct author/approver identities.
5. Verify upstream mode: sandbox only in development, disabled until real adapters
   pass conformance.
6. Verify NAM profile and enforcement setting.
7. Validate `ACTION_REGISTRY_PATH` when configured: closed actions, unique versions,
   OpenAPI digests/operations, allowed hosts, secret references, and reconciliation.
8. Start the API; `/health` reports process/version and `/ready` verifies stores,
   active policy, and provider-bundle state.
9. Verify `/api/v1/actions/catalog` contains expected bindings.
10. Verify `/api/v1/operations/audit-integrity`.

## Required production configuration

- `ENVIRONMENT=production`, `AUTH_ENABLED=true`;
- production JWT/issuer configuration and explicit CORS/rate limits;
- domain/core and policy repository adapters with conformance evidence;
- separate ADK session database;
- secret-managed `POLICY_SIGNING_KEY` and versioned key ID;
- different policy author/approver identities;
- approved jurisdiction fixture with enforcement enabled;
- real provider adapters and callback authentication;
- provider credentials outside prompts, ADK state, and logs.
- versioned action registry and pinned OpenAPI files, or reviewed Python connectors;

Production rejects sandbox mode. With adapters disabled, upstream endpoints return
`503` and consequential effects fail closed.

## Workers and reconciliation

Authorization atomically creates an outbox entry, then the application service
attempts the first provider dispatch synchronously so the confirming host can receive
an authoritative result. Run the action worker continuously or invoke
`/api/v1/operations/workers/actions:run` for controlled development. It leases due
records, dispatches only records still in `authorized`, settles records already made
terminal by the request path, applies exponential retry only to local worker failures,
and quarantines repeated processing errors. The outbox is recovery durability, not a
second normal dispatch path.

Monitor `unknown` actions and run the reconciliation worker. It queries provider
state; stale `dispatched` records become ambiguous after the configured delay.
Repeated `unknown` queries also wait for that delay to avoid hammering a provider.
Never redispatch to discover success. Alert when unknown age exceeds the
procedure-owned deadline.

Proposal `confirmed` is not provider success. Monitor the linked action. Proposal
expiry is lazy in v3.2, so retention/metrics may see pending records until read.

Run the continuous process as
`python -m workflow_engine.worker --poll-seconds 2`. Docker Compose defines a
separate worker service. Stop it before migrations, provider cutover, or rollback;
expired leases are recovered after restart.

## Operational endpoints

- `/api/v1/operations/actions` — status and outcomes;
- `/api/v1/operations/outbox` — pending/leased/failed/quarantined/delivered work;
- `/api/v1/operations/conversation-quarantine` — provider ordering gaps;
- `/api/v1/operations/delivery-receipts` — channel delivery callbacks;
- `/api/v1/operations/audit-integrity` — local hash-chain check;
- `/api/v1/metrics` — action/outbox counts, policies, adapter/profile state.

Restrict these routes with administrative RBAC and network policy.

## Handoff

Monitor requested, queued, accepted, connected, timeout, reassignment, failure,
resolution, and bot re-entry independently. Queue acknowledgment is not connection.
Callbacks must be authenticated, replay-protected, and transition-valid.

## Backup, recovery, and rollback

Back up core/policy, business, ADK, and provider records according to their distinct
retention. Recovery tests prove action idempotency, outbox lease recovery, unknown
reconciliation, provider-scoped inbox dedupe, sequence quarantine, policy version
lock, handoff reconstruction, and audit verification.

During rollback, stop all v3 dispatch workers before starting another version. Never
run two versions that disagree on command schema or idempotency concurrently.

Back up the exact registry and pinned OpenAPI documents used by each release. Keep
old connector code/contracts until queued and unknown actions using those versions
are terminal. Changing the active binding invalidates pending proposals.

## Connector incident handling

- Timeout/network ambiguity: retain `unknown` and query reconciliation.
- OpenAPI digest mismatch: treat startup failure as a change-control event.
- Credential failure: rotate the referenced secret; never configure one inline.
- Host change: review the allowlist and pinned contract; callers cannot override it.
- WebSocket-only provider: deploy a reviewed Python connector; the declarative WS
  binding is contract-only.

## Canary

Canary by procedure, channel, provider, and risk. Advancement requires zero
unauthorized effects, complete required evidence, no overdue unknown outcomes,
provider conformance, acceptable latency/error budget, and truthful handoff/delivery
status. Models/prompts can roll back independently from case/policy state.

## Observability boundary

`/api/v1/metrics` returns authenticated JSON, not Prometheus format. Structured
logs and correlation IDs are implemented; Prometheus exporters, OpenTelemetry,
dashboards, and alert routing are not packaged.

At minimum, deployments should alert on old pending outbox entries, unknown action
age, quarantine growth, worker inactivity, invalid active policy, audit-chain
failure, provider error/latency, and readiness failure.
