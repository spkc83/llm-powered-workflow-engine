# Testing and Verification

The suite separates deterministic correctness from external model/provider quality.

## Layers

- Unit: procedures, state, RBAC, reasoning, guardrails, action specs and settings.
- Persistence/integration: SQLite migrations, audit chain, outbox, policy restart,
  dedupe/order, handoff CAS and reconciliation.
- API: FastAPI request/response, OpenAPI contracts, auth boundaries and sandbox flow.
- UI contract: operator-client environment, bearer header, v3 paths and Shiny import.
- External conformance: deployment provider adapters must test success, rejection,
  duplicate, ordering gap, pre/post-commit timeout and reconciliation.

Run `pytest -q`, Ruff, mypy, compileall, `git diff --check`, Docker Compose config,
documentation links, OpenAPI parity, migration smoke and dependency audit before release.

## What tests do not prove

- Gemini availability or response quality under a real API account.
- Real STT/TTS audio quality, telephony signaling, chat delivery or contact-center behavior.
- Legal approval of the NAM/Reg E profile.
- Performance or multi-node correctness of a deployment-supplied database adapter.

Release evidence must list skipped live-provider/browser tests instead of treating
the deterministic suite as proof of those external systems.
