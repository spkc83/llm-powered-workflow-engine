# Changelog

## Unreleased

No unreleased changes documented.

## [3.2.0] - 2026-07-13

### Added

- Trusted conversation-to-action bridge with durable proposals, authoritative
  previews, expiry, actor/customer ownership, and atomic confirmation/cancellation.
- Structured action proposals in chat responses and Shiny confirmation cards with
  confirm, cancel, authoritative status, outcome, and event-history views.
- Proposal-only ADK tools for every closed-catalog consequential action; model calls
  cannot directly perform business effects.
- Action catalog, proposal lifecycle, and action-status REST/Swagger endpoints.
- Startup-validated per-action connector registry supporting SQLite demo bindings,
  pinned REST/OpenAPI bindings, and trusted Python connector factories.
- Declarative WebSocket provider binding contract with explicit validation-only
  status; no generic WebSocket dispatch runtime is claimed.
- Read-only reference-data resource adapters for versioned demo authority checks.
- Authenticated stateless Streamable HTTP MCP façade with proposal/status tools,
  catalog/proposal resources, and safety/workflow prompts; no execution authority.

### Changed

- Refunds now use the common typed consequential-action payload and gateway path.
- Development demonstrations use the same proposal/confirmation/gateway controls as
  provider deployments instead of legacy direct-write model tools.
- Authorized commands stamp immutable connector binding and contract versions.
- Version advanced to 3.2.0.

### Security

- Confirmation is host-only and derives actor/customer/evidence from trusted server
  context; model inputs cannot select provider URLs, credentials, policy, or binding.
- Confirmation fails on ownership mismatch, expiry, resource-version change,
  connector-binding change, missing consent/approval, or conflicting lifecycle state.
- REST registry rejects unknown actions, inline secrets, disallowed hosts, unpinned
  OpenAPI drift, incomplete asynchronous reconciliation, and insecure production URLs.

### Documentation

- Rewrote architecture, action bridge, API, integration, UI, configuration,
  operations, testing, threat-model, current-state, and roadmap documentation for
  the actual v3.2 implementation and its remaining limitations.

## [3.1.0] - 2026-07-12

### Added
- Trusted complete provider-bundle loading for operational `provider` mode.
- Separate continuously supervised action/reconciliation worker process.
- Backend readiness endpoint and Shiny system-status view.
- UI client, documentation parity, provider-bundle, and readiness tests.
- Current-state, configuration, UI, and testing guides plus expanded architecture.

### Changed
- Shiny console now honors `BACKEND_URL`/`BACKEND_AUTH_TOKEN` and canonical v3 APIs.
- Production reference Compose uses the documented single-API-worker SQLite topology.
- README rewritten around real architecture, assumptions, supported features, and limits.
- Removed inactive Prometheus/OpenTelemetry configuration flags.

## Documentation and licensing

- Added an explicit MIT license and contributor attribution policy.

## [3.0.0] - 2026-07-12

### Added
- One REST/WebSocket/IVR conversation service, provider-scoped dedupe, and sequence quarantine.
- Atomic action outbox, lease worker, retry quarantine, and reconciliation worker.
- Closed typed contracts for all cataloged consequential action families.
- Durable policy repository, signing key IDs, approval/activation/retirement APIs.
- Provider-neutral STT, TTS, telephony, chat, action, and human-agent interfaces.
- Truthful SQLite development sandbox with failure injection and delivery receipts.
- Configurable NAM operational controls and audit hash-chain verification.
- Swagger schemas/examples, operational APIs, and detailed integration documentation.

### Changed
- Upgraded Google ADK to 2.4.0, Starlette to 1.3.1, PyJWT to 2.13.0,
  pytest to 9.1.1, and pytest-asyncio to 1.4.0 after dependency audit.
- WebSocket responses now use the complete safety pipeline and buffer consequential output.
- Production defaults to disabled upstream adapters and rejects sandbox mode.
- Tool catalog records gateway-enforced idempotency for consequential operations.

### Security
- Client values cannot self-declare verified action parameters; adapters reload authoritative resources.
- Post-commit provider timeouts reconcile without duplicate dispatch.
- Stale dispatched attempts reconcile after process death without redispatch, and
  delayed actions remain verifiable against retired signed policy history.
- Secret DTMF is redacted by the development STT contract.

## [2.0.0] - 2026-07-12

### Added
- Database-agnostic durable case/fact/action kernel with SQLite adapter.
- Typed fact authority, evidence provenance, optimistic concurrency, and procedure
  version locking.
- Independent action gateway, idempotency, unknown outcomes, and reconciliation.
- Gateway-backed refund vertical slice and deterministic Reg E decisions.
- Signed policy approval with author/approver separation and NAM profile.
- Shared chat/IVR inbox dedupe, IVR confidence/readback contract, response
  contracts, and durable human handoff.
- Bounded ADK 2 graph, replay harness, rollout gates, tool-control catalog, and
  actor/customer identity binding.
- End-user, channel, operations, governance, migration, security, support, and
  release documentation.

### Changed
- Upgraded Google ADK from 1.9.0 to 2.1.0 and FastAPI to 0.139.0.
- Separated ADK session storage from domain/core storage.
- Refund tools reload authoritative order data and require explicit consent.
- REST and WebSocket sessions are isolated by authenticated actor/customer pair.

### Security
- Consequential tools fail closed in production until independently controlled.
- Cross-customer session and tool access is denied.
- Duplicate messages and refund actions are suppressed by durable uniqueness.
