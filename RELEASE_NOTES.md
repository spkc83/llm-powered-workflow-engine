# LLM-Powered Workflow Engine v3.0.0

v3 completes the provider-neutral production control-plane foundation. Chat and IVR
now use one response-safety pipeline; consequential operations use closed typed
action contracts, atomic outbox delivery, idempotent connectors, and reconciliation.
Policy governance persists across restart, and upstream dependencies have truthful
development adapters plus Swagger contracts.

## Highlights

- Shared REST/WebSocket/IVR `ConversationService` with provider-scoped dedupe and
  durable sequence-gap quarantine.
- Typed gateway contracts for store credit, case updates, EFT disputes,
  provisional credit, escalation, notes, account restrictions, SAR submission,
  and alert closure; specialized refund slice retained.
- Atomic action/outbox insertion, SQLite-compatible leases, retry quarantine,
  unknown-outcome reconciliation, and operational APIs.
- Durable signed policy packages with separate author/approver, key IDs, activation,
  retirement, and one active procedure/jurisdiction package.
- STT, TTS, telephony, chat delivery/receipt, action-system, and human-agent ports.
- SQLite sandbox emulates success, rejection, pre-commit timeout, and post-commit
  timeout and marks all outputs simulated. Production rejects sandbox mode.
- Configurable NAM operational consent/retention controls and secure DTMF handling.
- Truthful human handoff lifecycle from request through connection/resolution.
- Append-order audit hash chain, action/outbox/quarantine/receipt metrics, and
  integrity endpoint.
- Detailed Swagger/OpenAPI examples and upstream integration documentation.
- Security-updated dependency baseline: Google ADK 2.4, Starlette 1.3.1,
  PyJWT 2.13, pytest 9.1.1, and pytest-asyncio 1.4.

## Upgrade notes

Follow `docs/migration.md`. Deploy first with adapters disabled, migrate/back up the
database, verify audit backfill and policy persistence, then conformance-test and
canary each real provider. The built-in provider implementations are development
emulators, not production integrations.

## Compatibility

Legacy `/api/...`, `/api/v1/chat`, and `/api/v1/ivr/turns` remain. Canonical new
integrations should use `/api/v1/conversations/turns`, typed core actions, and the
provider contracts described in `docs/integration-guide.md`.
