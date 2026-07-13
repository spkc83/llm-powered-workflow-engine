# LLM-Powered Workflow Engine

A deterministic workflow control plane with bounded Google ADK 2.4 conversation
support. It is designed for customer-service, fraud, claims, and regulated financial
workflows where a model may propose intent and wording but must never authorize or
execute a consequential action.

Version: 3.1.0 · License: [MIT](LICENSE) · Maintainer: [spkc83](CONTRIBUTORS.md)

## What this repository is

The application combines:

- a FastAPI REST/WebSocket service;
- a durable case, fact, policy, action, inbox, outbox, and handoff kernel;
- Google ADK agents for conversational routing and response generation;
- deterministic procedure, policy, reasoning, and compliance checks;
- provider-neutral STT, TTS, telephony, chat, action, and human-handoff ports;
- truthful SQLite development emulators;
- a Shiny development/operator console.

It is not a complete bank, contact center, telephony platform, or production customer
portal. Vendor adapters, credentials, TLS, secret management, external monitoring,
legal approval, and deployment-specific data retention remain operator responsibilities.

See [Current Application State](docs/current-state.md) before evaluating features.

## Architecture and authority

```text
Chat REST / WebSocket / IVR transcript
                  │
       authentication + customer binding
                  │
 provider-scoped inbox, dedupe, sequence quarantine
                  │
       shared ConversationService safety pipeline
                  │
      ADK proposal and response-wording layer
                  │
 deterministic procedure / policy / jurisdiction checks
                  │
 CoreStore: cases + verified facts + action authorization
                  │  same transaction
             durable outbox
                  │
       supervised ActionDeliveryWorker
                  │
 sandbox emulator or deployment ProviderBundle
                  │
       outcome / unknown / reconciliation evidence
```

The model, prompt, tool arguments, channel payload, and ADK session are untrusted.
Consequential operations require authenticated permissions, customer binding,
authoritative resource reload, a signed active policy, verified facts, consent or
approval where required, an idempotency key, and durable dispatch evidence.

Detailed component, lifecycle, and failure semantics are in
[Core Engine Architecture](docs/core-engine.md) and the
[Threat Model](docs/threat-model.md).

## Capability summary

| Capability | Current state |
|---|---|
| Core case/fact/action engine | Implemented with SQLite reference store. |
| Chat REST and WebSocket | Implemented through one guarded turn pipeline. |
| IVR | Final-transcript processing and contracts implemented; no real call control. |
| STT/TTS/telephony/chat delivery | Simulated locally; real adapters are deployment-supplied. |
| Typed consequential actions | Implemented with durable outbox and reconciliation. |
| Human handoff | Durable lifecycle plus local queue emulator; real platform adapter external. |
| Policy governance | Durable draft/approve/activate/retire and key rotation. |
| Database portability | Ports/factories implemented; only SQLite ships. |
| UI | Development/operator Shiny console, not customer production UI. |
| Observability | Structured logs, health/readiness, JSON metrics and audit verification. |

## Quick start

Prerequisites: Python 3.11+ and a Google AI API key for live model responses.
Deterministic tests and most sandbox APIs do not require live provider credentials.

```bash
git clone https://github.com/spkc83/llm-powered-workflow-engine.git
cd llm-powered-workflow-engine
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# set GOOGLE_API_KEY in .env
uvicorn main:app --port 8000
```

Open Swagger at <http://localhost:8000/docs>. Health is `/health`; readiness is
`/ready`.

Start the operator console separately:

```bash
BACKEND_URL=http://localhost:8000 shiny run app_ui.py --port 8001
```

Or run backend, UI, and worker together:

```bash
docker compose up --build
```

Development creates and seeds the SQLite reference database. Production forbids
automatic reference-data seeding and sandbox upstream mode.

## Runtime modes

- `UPSTREAM_MODE=disabled`: fail closed; consequential/provider endpoints return 503.
- `UPSTREAM_MODE=sandbox`: development-only SQLite emulators with `simulated: true`.
- `UPSTREAM_MODE=provider`: loads a trusted `PROVIDER_BUNDLE_FACTORY` supplying all
  provider ports. The repository does not ship vendor credentials or SDK adapters.

The API and action worker are separate processes. The included SQLite production
fallback uses one API worker and one action worker sharing a local volume. Larger or
multi-node deployments must supply conforming stores.

## Main APIs

- `POST /api/v1/conversations/turns` — canonical chat/IVR turn.
- `POST /api/v1/chat` and `WS /api/v1/ws/chat` — chat compatibility transports.
- `POST /api/v1/core/actions` — typed consequential actions.
- `POST /api/v1/core/refunds` — refund vertical slice.
- `/api/v1/integrations/...` — STT, TTS, telephony, chat and contract surfaces.
- `/api/v1/handoffs` — durable human-handoff lifecycle.
- `/api/v1/policies` — policy governance.
- `/api/v1/operations/...` — actions, outbox, reconciliation, quarantine, receipts,
  audit integrity and worker controls.

Use [API Reference](docs/api.md), live Swagger, and the
[Upstream Integration Guide](docs/integration-guide.md) for schemas and examples.

## Procedures and supported demonstrations

YAML procedures cover customer-service refunds, complaints, fraud alert triage, and
Regulation E EFT disputes. Z3/SymPy checks and domain compliance rules verify selected
claims and calculations. These are engineering demonstrations, not legal advice.

Consequential action specifications currently cover refunds, store credit, case
status, EFT disputes, provisional credit, escalation, case notes, account flags,
SAR submission, and alert closure. In production, model-visible legacy write tools
remain frozen; effects go through the typed action gateway.

See [Procedure Authoring](docs/procedures.md) and
[Policy and Data Governance](docs/governance.md).

## Configuration

Configuration is environment-driven and validated at startup. Important groups are:

- core, reference, policy, and ADK session databases;
- JWT/RBAC and CORS;
- policy signing and jurisdiction;
- upstream mode and provider bundle;
- action worker leases/reconciliation;
- LLM, logging, rate limits and operator UI.

The complete source-aligned reference is [Configuration](docs/configuration.md).

## Testing

```bash
pytest -q
ruff check app_ui.py main.py workflow_engine tests --ignore E402
mypy --ignore-missing-imports --follow-imports=skip main.py workflow_engine
python -m compileall -q app_ui.py main.py workflow_engine tests
docker compose config --quiet
```

The deterministic suite does not prove live Gemini quality, real provider behavior,
legal approval, or a deployment-supplied database. See [Testing](docs/testing.md).

## Documentation

- [Documentation index](docs/README.md)
- [Current state and limitations](docs/current-state.md)
- [Core architecture](docs/core-engine.md)
- [Configuration](docs/configuration.md)
- [API](docs/api.md)
- [Chat and IVR](docs/channels.md)
- [Provider integration](docs/integration-guide.md)
- [UI console](docs/ui.md)
- [Storage](docs/database.md)
- [Operations](docs/operations.md)
- [Threat model](docs/threat-model.md)
- [Migration](docs/migration.md)
- [Testing](docs/testing.md)
- [Security](SECURITY.md) and [Support](SUPPORT.md)

## Contributing and license

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CONTRIBUTORS.md](CONTRIBUTORS.md).
Released under the [MIT License](LICENSE).
