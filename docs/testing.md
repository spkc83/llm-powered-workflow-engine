# Testing and Verification

The test strategy separates deterministic engine correctness from external model,
provider, browser, and deployment quality.

## Test layers

| Layer | Primary files | What it proves |
|---|---|---|
| Domain unit | `test_core_engine.py`, `test_reasoning.py`, `test_reg_e_compliance.py` | Rules, authority, state, decisions, response contracts. |
| Procedure/agent construction | `test_procedure_*.py`, `test_agent_*.py`, `test_tool_catalog.py` | YAML loading, routing, tool classification, production freeze, agent graph. |
| Security | `test_auth.py`, `test_settings.py`, `test_guardrails.py` | JWT/RBAC, production validation, response/tool controls. |
| Persistence | `test_database.py`, `test_v3_integrations.py` | SQLite schema, migration, audit chain, actions, outbox, policy, inbox, handoff. |
| Action bridge | `test_action_bridge.py`, `test_action_proposal_tools.py` | Proposal-only tools, ownership, evidence, stale data, replay, and typed submission. |
| Connector registry | `test_action_registry.py`, `test_resource_adapters.py` | Closed catalog, production rejection, OpenAPI pinning, REST timeout/reconcile, resources. |
| API | `test_api.py` | FastAPI response shapes, routes, Swagger/OpenAPI surface, sandbox action flow. |
| UI contract | `test_ui_client.py` | Configured backend/token, canonical paths, client behavior, Shiny import/ASGI render. |
| Documentation contract | `test_documentation_contract.py` | Version/config/route documentation remains aligned with source. |

## Run locally

```bash
pytest -q
ruff check app_ui.py main.py workflow_engine tests --ignore E402
mypy --ignore-missing-imports --follow-imports=skip main.py workflow_engine
python -m compileall -q app_ui.py main.py workflow_engine tests
docker compose config --quiet
git diff --check
```

## Important test semantics

### Deterministic versus model evaluation

Core correctness tests do not depend on a live Gemini response. API and agent tests
patch or control model-facing behavior. This makes policy, authorization,
idempotency, and recovery tests repeatable.

Live model evaluation is a separate quality activity. It should measure routing,
clarification, groundedness, helpfulness, and regression across a versioned prompt
corpus without treating model output as authorization evidence.

### Sandbox versus provider conformance

Sandbox tests prove the engine's expected provider semantics:

- success and rejection;
- timeout before commit;
- timeout after commit;
- stable idempotency;
- no blind redispatch;
- query-only reconciliation;
- duplicate and sequence-gap behavior;
- handoff lifecycle truthfulness.

A real `ProviderBundle` must pass equivalent tests in the deployment environment.
The repository cannot prove a vendor implementation it does not contain.

Registry tests use an in-memory HTTP transport. They do not certify a real
service, credential flow, DNS/TLS environment, or provider reconciliation. Every
deployment binding needs timeout-before/after-commit and idempotency conformance.

### UI verification

Current tests cover the typed API client and Shiny ASGI rendering. They do not
exercise every browser click, reactive update, responsive layout, accessibility
behavior, or identity flow.

Proposal-card helper and client tests are not browser automation. `test_mcp_server.py`
proves the MCP façade exposes only proposal/status tools plus safe resources/prompts,
rejects trusted fields, and builds a stateless Streamable HTTP app. It is not a live
host interoperability test. No generic WebSocket provider runtime exists; its tests
prove validation/fail-closed behavior. Customer chat WebSocket is separate.

## What the suite does not prove

- Gemini availability or response quality with production credentials;
- real STT/TTS audio quality;
- telephony signaling or recording behavior;
- external chat delivery and receipt authenticity;
- contact-center staffing and transfer SLAs;
- real business-system action semantics;
- legal approval of NAM/Reg E configuration;
- performance or multi-node correctness of a deployment database;
- TLS, secret manager, ingress, SIEM, backup, and restore supplied by an operator.

## Release gate

A release should include:

1. full deterministic tests;
2. Ruff, mypy, compile, and diff checks;
3. migration smoke from the previous release;
4. OpenAPI and documentation contract checks;
5. Docker Compose backend/UI/worker startup;
6. readiness and worker recovery verification;
7. dependency and container vulnerability audit;
8. provider conformance results for each enabled provider;
9. live model evaluation when prompts/models change;
10. an explicit list of skipped external checks and their owner.

Do not report “all tests pass” as proof of external providers or legal compliance.
