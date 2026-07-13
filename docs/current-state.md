# Current Application State

Last verified: v3.1.0 code line, 2026-07-12.

This page is the authoritative feature-status statement. “Implemented” means the
repository contains working code and automated coverage. “Sandbox” means a local,
explicitly simulated implementation. “Deployment-supplied” means the contract and
loader exist but no vendor implementation or credentials ship here.

| Area | Status | What is available |
|---|---|---|
| Core cases, facts, actions | Implemented | SQLite durable store, typed authority, optimistic concurrency, idempotency. |
| Policy governance | Implemented | Draft, separate approval, signing, activation, retirement, key rotation. |
| Chat REST/WebSocket | Implemented | Shared turn service, identity binding, dedupe/order, guardrails. |
| IVR turn processing | Implemented | Normalized final transcripts, confidence/readback and jurisdiction controls. |
| STT/TTS/telephony | Sandbox + deployment-supplied | Local stubs are simulated; provider bundle supplies real implementations. |
| Chat delivery | Sandbox + deployment-supplied | Local receipt ledger; real delivery comes from a provider bundle. |
| Consequential actions | Implemented core, sandbox/provider effect | Typed authorization/outbox/reconciliation; local effect emulator or provider bundle. |
| Human handoff | Sandbox + deployment-supplied | Durable lifecycle and local queue; real contact-center connector is external. |
| Database portability | Interface + deployment-supplied | SQLite ships; other stores must implement and pass the same behavior. |
| Worker processing | Implemented | Separate `python -m workflow_engine.worker` process plus admin run-once endpoints. |
| UI | Development/operator console | Shiny UI uses v3 APIs; it is not a production customer portal. |
| Observability | Partial | Structured logs, health, operational JSON metrics and audit verification; no packaged Prometheus/OTel exporter yet. |
| Production deployment | Reference boundary | Fail-closed defaults. Real secrets, TLS, providers, durable external monitoring and approved storage remain deployment obligations. |

## Important assumptions

- Models and ADK output are untrusted proposals, never authorization.
- SQLite is the default and reference adapter. The supported production SQLite
  topology is one API worker plus one action worker on a shared local volume.
- NAM controls are an engineering profile, not legal advice or regulatory approval.
- The sandbox contains no real audio, telephony, chat delivery, contact-center, or
  external business-system integration.
- `UPSTREAM_MODE=provider` requires `PROVIDER_BUNDLE_FACTORY`; startup fails without it.

## Explicitly out of scope

- A customer-grade web/mobile frontend.
- Vendor credentials or branded provider SDKs.
- Legal certification, case-management staffing, or contact-center workforce management.
- A packaged PostgreSQL adapter; database ports are available for deployment implementations.
