# Changelog

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
