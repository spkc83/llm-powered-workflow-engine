# LLM-Powered Workflow Engine v3.2.0

v3.2 connects customer conversation to the typed action core without making the
model an authorization boundary.

## Application changes

- Consequential ADK tools queue intent only and cannot perform an effect.
- Trusted host code creates durable actor/customer-bound proposals with an
  authoritative preview, expiry, resource version, policy/procedure context,
  idempotency, and connector binding versions.
- Shiny renders structured proposal cards with host-only confirm/cancel and
  authoritative action/event status.
- Refund uses the common typed action service and gateway path.
- A per-action registry supports SQLite demo, pinned REST/OpenAPI, and trusted
  Python connectors. WebSocket action bindings are contract-only and fail closed.
- An authenticated Streamable HTTP MCP façade exposes proposal/status tools,
  resources, and safety prompts without confirmation or execution authority.
- Swagger exposes catalog, proposal lifecycle, and action status endpoints.

## Documentation

Architecture, action bridge, current-state, configuration, API, UI, integration,
storage, governance, security, operations, testing, migration, user, and roadmap
guides describe the exact v3.2 path. They distinguish implemented, simulated,
contract-only, deployment-supplied, and missing capabilities.

## Verification boundary

The suite covers bridge, registry, REST ambiguity/reconciliation, authoritative
resources, API/OpenAPI, UI client/helpers, persistence, and existing core behavior.
It does not certify a vendor provider, complete browser UX, legal interpretation,
or a deployment database. See `docs/testing.md`.

## Remaining deployment obligations

No vendor adapters, generic WebSocket provider runtime, MCP confirmation/execution,
production UI, or production database adapter ships. Real providers, TLS, identity, secrets,
monitoring/export, approved storage/retention, and legal approval remain deployment
responsibilities.
