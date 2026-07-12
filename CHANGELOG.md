# Changelog

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
