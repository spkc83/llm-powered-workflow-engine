# LLM-Powered Workflow Engine

A deterministic, omnichannel workflow engine with bounded [Google ADK](https://adk.dev/) 2.1 interaction capabilities. Models propose intent, facts, and wording; typed policy, durable cases, and an independent action gateway control business actions. Designed for customer service, fraud operations, and claims workflows at financial institutions.

Agents follow YAML-defined step-by-step procedures while maintaining natural conversational interaction, with runtime enforcement via a stateful procedure executor.

## Architecture

```text
Chat REST/WS + IVR provider webhooks
                |
     authenticated actor/customer binding
                |
 shared conversation inbox + ordering quarantine
                |
      bounded ADK 2.4 interaction layer
  (intent/fact proposals and response text only)
                |
 deterministic procedure router + CoreEngine
                |
  durable cases / typed facts / policy package
                |
 authorization + atomic outbox + ActionGateway
                |
 provider adapter / sandbox / human queue
```

The model and ADK session are never authoritative for consequential actions.
`CoreEngine` reloads domain records, validates ownership and eligibility, commits
verified facts, creates an idempotent action, and dispatches it through the action
gateway. SQLite is the default store; the `CoreStore` protocol supports additional
database adapters without changing engine semantics. ADK sessions use a separate
ADK 2.x database.

v3 includes provider-neutral STT, TTS, telephony, chat-delivery, action, and
human-agent ports. Development uses truthful SQLite sandbox adapters; production
defaults to disabled and rejects sandbox mode. Swagger UI at
<http://localhost:8000/docs> contains live request schemas and examples. See the
[upstream integration guide](docs/integration-guide.md).

### Agent Hierarchy

```
router_agent (configurable — default: Gemini 2.5 Flash)
├── customer_service_agent — orders, refunds, returns, complaints, EFT disputes
│   └── Tools: lookup_order, search_orders, get_customer_profile,
│             issue_refund, update_case_status, escalate_to_supervisor,
│             add_case_note, get_knowledge_article,
│             lookup_dispute, check_dispute_eligibility,
│             file_eft_dispute, issue_provisional_credit
├── fraud_ops_agent — alert triage, investigation, account actions
│   └── Tools: get_fraud_alert, get_account_transactions,
│             check_device_fingerprint, flag_account,
│             submit_sar, close_alert, escalate_to_supervisor,
│             add_case_note
└── general_agent — greetings, general questions, policy inquiries, fallback
    └── Tools: get_knowledge_article
```

The **router agent** examines user intent and delegates to the appropriate specialist. Each specialist receives procedure guidance. Consequential tool names shown above are proposal/legacy development surfaces and remain frozen for production model execution; real effects use the typed action service and independent gateway.

## Quick Start

### Prerequisites

- Python 3.11+
- A [Google AI API key](https://aistudio.google.com/apikey) (for Gemini)

### Setup

```bash
# Clone and enter the project
git clone <repo-url>
cd llm-powerd-workflow-engine

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add your GOOGLE_API_KEY
```

### Run

**Backend** (FastAPI + ADK agents):

```bash
uvicorn main:app --port 8000
```

The database (`data/workflow.db`) is automatically created and seeded with sample data on first startup.

**Chat UI** (Shiny for Python):

```bash
shiny run app_ui.py --port 8001
```

Then open http://localhost:8001 in your browser.

## Documentation

See the [documentation index](docs/README.md) for customer/operator guidance,
chat and IVR contracts, API reference, core architecture, policy governance,
operations, migration, threat model, security, support, and release notes.

**ADK dev tools** (alternative to the Shiny UI):

```bash
adk web
```

### Docker

```bash
# Development
docker compose up

# Production (with auth, rate limiting, multi-worker)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### Database Management

The database initializes automatically when the backend starts. You can also manage it standalone:

```bash
# Initialize and seed (idempotent — safe to run repeatedly)
python -m workflow_engine.database

# Reset: delete existing DB and recreate from scratch
python -m workflow_engine.database --reset
```

Use `--reset` after schema changes or when you want fresh sample data.

### Run Tests

```bash
pytest tests/ -v
```

## Project Structure

```
.
├── main.py                         # FastAPI backend — versioned API, middleware, lifecycle
├── app_ui.py                       # Shiny for Python chat UI
├── requirements.txt                # Direct Python dependencies
├── constraints.txt                 # Pinned Phase 0 direct-dependency baseline
├── Dockerfile                      # Multi-stage container build
├── docker-compose.yml              # Dev deployment
├── docker-compose.prod.yml         # Production overlay
├── .dockerignore                   # Docker build exclusions
├── .env.example                    # Environment variable reference
├── .env                            # API keys (not committed)
│
├── procedures/                     # YAML workflow definitions
│   ├── customer_service_refund.yaml
│   ├── customer_service_complaint.yaml
│   ├── fraud_ops_alert_triage.yaml
│   └── cs_eft_dispute.yaml         # Reg E EFT dispute resolution
│
├── workflow_engine/                # Core engine package
│   ├── settings.py                 # Centralized config (Pydantic BaseSettings)
│   ├── errors.py                   # Structured error hierarchy with error codes
│   ├── logging_config.py           # Structured logging with correlation IDs
│   ├── config.py                   # LLM model config (Gemini via settings)
│   ├── agent.py                    # ADK entry point — registry + root_agent
│   │
│   ├── agents/                     # Agent factories
│   │   ├── router.py               # Router agent + general agent
│   │   ├── customer_service.py     # Customer service agent factory
│   │   ├── fraud_ops.py            # Fraud operations agent factory
│   │   ├── guardrails.py           # Output filtering, tool arg validation, behavior steering
│   │   ├── reasoning.py           # Z3/SymPy automated reasoning engine
│   │   └── compliance.py          # Domain-specific compliance checks (Reg E, financial)
│   │
│   ├── auth/                       # Authentication & authorization
│   │   ├── models.py               # Role, Permission, UserContext models
│   │   ├── rbac.py                 # Role-based access control mappings
│   │   └── jwt_handler.py          # JWT token creation and verification
│   │
│   ├── audit/                      # Compliance audit trail
│   │   └── logger.py               # Append-oriented audit logging with DB persistence
│   │
│   ├── channels/                   # Omni-channel abstraction
│   │   ├── base.py                 # Channel interface, InboundMessage, OutboundMessage
│   │   ├── http.py                 # HTTP REST and WebSocket adapters
│   │   └── ivr.py                  # Provider-neutral IVR/ASR normalization
│   │
│   ├── middleware/                  # FastAPI middleware stack
│   │   ├── auth.py                 # JWT authentication middleware
│   │   ├── correlation.py          # Request correlation ID tracing
│   │   ├── error_handler.py        # Structured error responses
│   │   └── rate_limiter.py         # In-memory rate limiting
│   │
│   ├── tools/                      # Classified model read/proposal tools; production writes frozen
│   │   ├── crm_tools.py            # lookup_order, search_orders, get_customer_profile, issue_refund, issue_store_credit, update_case_status
│   │   ├── fraud_tools.py          # get_fraud_alert, get_account_transactions, check_device_fingerprint, flag_account, submit_sar, close_alert
│   │   ├── common_tools.py         # escalate_to_supervisor, add_case_note, get_knowledge_article
│   │   └── dispute_tools.py        # lookup_dispute, check_dispute_eligibility, file_eft_dispute, issue_provisional_credit
│   │
│   ├── core/                       # Cases, facts, policy, outbox, workers, action gateway
│   ├── conversation/               # Shared chat/IVR service, inbox, response/handoff contracts
│   ├── integrations/               # Provider ports and truthful SQLite dev adapters
│   │
│   ├── database/                   # Persistence layer
│   │   ├── __main__.py             # Standalone DB init: python -m workflow_engine.database [--reset]
│   │   ├── db.py                   # Schema, connection helpers, transaction support
│   │   ├── seed.py                 # Seed data (customers, orders, alerts, etc.)
│   │   └── repository.py           # Repository pattern — typed data access objects
│   │
│   ├── procedures/                 # Procedure loading and execution
│   │   ├── loader.py               # YAML parser, validator, instruction builder
│   │   ├── registry.py             # Procedure registry with intent mapping
│   │   └── executor.py             # Stateful procedure executor (state machine)
│   │
│   └── state/                      # Workflow state tracking
│       └── workflow_state.py       # initialize, step tracking, completion, escalation
│
├── data/                           # SQLite database (created at runtime)
│   └── workflow.db
│
├── docs/                           # Documentation
│   ├── api.md                      # API and channel contracts
│   ├── integration-guide.md        # Provider ports, callbacks, conformance
│   ├── database.md                 # Business/core/ADK persistence
│   ├── core-engine.md              # Authority boundaries and invariants
│   ├── threat-model.md             # Trust assumptions and threats
│   ├── operations.md               # Deployment, rollout, reconciliation, incidents
│   ├── migration.md                # v2 to v3 control-plane migration
│   └── procedures.md               # Procedure and governed-policy authoring
│
└── tests/                          # Unit, integration, API, identity, core, replay tests
    ├── test_database.py            # DB init, seed, query helpers
    ├── test_mock_tools.py          # All tool functions (async, uses temp DB)
    ├── test_workflow_state.py      # State tracking logic
    ├── test_procedure_loader.py    # YAML loading and validation
    ├── test_procedure_registry.py  # Registry and intent mapping
    ├── test_procedure_executor.py  # Stateful executor, transitions, branching
    ├── test_agent_factory.py       # Agent creation
    ├── test_agent_integration.py   # Integration tests
    ├── test_api.py                 # FastAPI endpoint tests
    ├── test_settings.py            # Configuration validation
    ├── test_errors.py              # Error hierarchy
    ├── test_auth.py                # JWT, RBAC, permissions
    ├── test_guardrails.py          # Output filtering, tool arg validation, steering pipeline
    ├── test_channels.py            # Channel abstraction, HTTP/WS adapters
    ├── test_audit.py               # Audit trail logging
    ├── test_reasoning.py           # Z3/SymPy automated reasoning engine
    └── test_reg_e_compliance.py    # Reg E compliance checks, dispute tools, disclosures
```

## Configuration

All configuration is centralized via [Pydantic BaseSettings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/). Settings are loaded from environment variables or `.env` files with full validation and type coercion.

See `.env.example` for the complete reference. Key settings:

| Variable | Description | Default |
|----------|-------------|---------|
| `ENVIRONMENT` | Runtime environment (`dev`, `staging`, `production`) | `dev` |
| `GOOGLE_API_KEY` | Google AI API key (required) | — |
| `LLM_MODEL` | Model name for all agents | `gemini-2.5-flash` |
| `DATABASE_URL` | Domain/core database URL | `sqlite+aiosqlite:///data/workflow.db` |
| `ADK_SESSION_DATABASE_URL` | Separate ADK 2.x session/event URL | `sqlite+aiosqlite:///data/adk_sessions_v2.db` |
| `POLICY_DATABASE_URL` | Durable policy repository URL; defaults to domain DB | `DATABASE_URL` |
| `UPSTREAM_MODE` | `disabled`, `sandbox`, or deployment-wired `provider` | sandbox in dev; disabled elsewhere |
| `SANDBOX_DATABASE_URL` | Development upstream emulator | `sqlite+aiosqlite:///data/upstream_sandbox.db` |
| `JURISDICTION_PROFILE` | Operational jurisdiction profile | `NAM` |
| `JURISDICTION_CONFIG_PATH` | Counsel-approved YAML/JSON profile override | — |
| `API_PREFIX` | API route prefix | `/api/v1` |
| `AUTH_ENABLED` | Enable JWT authentication | `false` |
| `AUTH_SECRET_KEY` | JWT signing secret | dev default |
| `JURISDICTION_PROFILE` | Active policy jurisdiction profile | `NAM` |
| `POLICY_SIGNING_KEY` | HMAC policy key; must change in production | dev default |
| `POLICY_AUTHOR` | Policy author identity | `operations-author` |
| `POLICY_APPROVER` | Separate policy approver identity | `risk-approver` |
| `RATE_LIMIT_ENABLED` | Enable request rate limiting | `false` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `LOG_FORMAT` | Log format (`text` or `json`) | `text` (dev) / `json` (prod) |
| `CORS_ORIGINS` | Allowed CORS origins | `["http://localhost:8001"]` |
| `REASONING_ENABLED` | Enable Z3/SymPy automated reasoning verification | `true` |
| `REASONING_MAX_ITERATIONS` | Max behavior steering rewrite iterations | `2` |
| `COMPLIANCE_ENABLED` | Enable domain-specific compliance checks | `true` |

## Key Concepts

### Procedures

Procedures are YAML files that define structured workflows as a sequence of steps. Each step has:

- **`id`** — unique identifier for the step
- **`instruction`** — natural language guidance for the agent
- **`action`** — step type: `collect_info`, `tool_call`, `evaluate`, or `inform`
- **Branching** — `next_step`, `on_success`/`on_failure`, `conditions`, or `options`

The procedure loader transforms YAML steps into agent instructions, and the **stateful procedure executor** tracks the current step, validates transitions, and enforces the branching logic at the engine level.

See [docs/procedures.md](docs/procedures.md) for the full procedure authoring guide.

### Procedure Executor (State Machine)

The `ProcedureExecutor` provides runtime enforcement of procedure progression:

- **Transition validation** — only allows transitions defined in the procedure graph
- **Step lifecycle hooks** — `on_enter` and `on_exit` hooks for each step
- **Progress tracking** — which steps have been completed, current step, timestamps
- **Audit integration** — every step transition is logged to the audit trail

```python
executor = ProcedureExecutor(procedure_def)
await executor.start(session_state)           # Starts at first step
await executor.transition("step_2", state)    # Validates and transitions
progress = executor.get_progress()            # {status, current_step, steps_completed, ...}
```

### Authentication & Authorization

The engine supports JWT-based authentication with role-based access control (RBAC):

| Role | Permissions |
|------|------------|
| `admin` | All permissions |
| `supervisor` | Full CS + fraud + read-only admin |
| `customer_service_rep` | Orders, refunds, cases, escalations |
| `fraud_analyst` | Fraud alerts, account flags, SAR filing |
| `readonly` | Read-only access to all domains |

Auth is disabled by default for development. Enable with `AUTH_ENABLED=true`.

### Audit Trail

Every compliance-critical action is recorded in an append-oriented audit trail.
Production deployments must add database permissions/tamper-evidence controls if
regulatory immutability is required:

- Refunds issued, accounts flagged, SARs submitted
- Procedure starts, step transitions, completions
- Full context: who, what, when, session, procedure, before/after state

### Channels (Omni-Channel)

The channel abstraction layer normalizes messages from different communication sources:

- **HTTP REST** — standard request/response chat
- **WebSocket** — real-time streaming responses
- **Extensible** — add SMS, email, WhatsApp, IVR adapters by implementing the `Channel` interface

### Agent Guardrails & Automated Reasoning

The guardrails system uses a **4-layer pipeline** that combines fast pattern matching with formal logic verification:

```
LLM Response
    │
    ▼
Layer 1: Pattern Rails (regex — fast first pass)
    → Redact internal data, flag unauthorized promises
    │
Layer 2: Reasoning Rails (Z3 SMT solver)
    → Verify LLM claims against formal procedure rules
    │
Layer 3: Compliance Rails (SymPy + domain rules)
    → Financial math verification, required disclosures, Reg E checks
    │
Layer 4: Behavior Steering (rewrite loop)
    → If INVALID: re-invoke LLM with feedback, re-verify (max 2 iterations)
    → If still invalid: return safe fallback response
    │
    ▼
Verified Response → Client
```

**Pattern Rails** (Layer 1) — existing regex-based checks that prevent agents from:
- Leaking internal data (step IDs, SQL queries, credentials)
- Making unauthorized promises or guarantees
- Providing unauthorized financial/legal advice

**Reasoning Rails** (Layer 2) — Z3 SMT solver verifies LLM claims deterministically:
- Extracts claims from LLM text (dollar amounts, day counts, approval/denial decisions)
- Converts YAML procedure conditions into Z3 formal logic constraints
- Verifies claims are **mathematically consistent** with business rules
- Returns VALID / INVALID / SATISFIABLE verdicts with cited rules

**Compliance Rails** (Layer 3) — domain-specific verification:
- **Financial accuracy** — SymPy verifies refund amounts, provisional credits, tax calculations
- **Required disclosures** — checks that mandated information is present per procedure step
- **Reg E compliance** — liability tier validation, investigation timeline accuracy, provisional credit math
- **Prohibited content** — blocks investment advice, legal advice, competitor referrals

**Behavior Steering** (Layer 4) — self-correcting pipeline:
- If verification fails, constructs a rewrite prompt with specific feedback
- Re-invokes the LLM with the violation details and rewrite hints
- Re-verifies the corrected response (up to 2 iterations)
- Falls back to a safe response if correction fails

Tool argument validation catches:
- Negative amounts, malformed IDs
- Oversized inputs (prompt injection prevention)

Configuration in `.env`:

| Variable | Description | Default |
|----------|-------------|---------|
| `REASONING_ENABLED` | Enable Z3/SymPy reasoning verification | `true` |
| `REASONING_MAX_ITERATIONS` | Max rewrite iterations for behavior steering | `2` |
| `COMPLIANCE_ENABLED` | Enable domain compliance checks | `true` |

### Regulation E (EFT Dispute) Compliance

The engine includes a complete **Regulation E** implementation for electronic fund transfer disputes, demonstrating the automated reasoning system in a real compliance scenario.

**Reg E Key Rules Enforced:**

| Rule | Enforcement |
|------|-------------|
| Consumer liability: $50 (2 days), $500 (60 days), unlimited (60+ days) | Z3 constraint verification + SymPy math |
| Investigation: 10 business days initial, 45/90 calendar days final | Required disclosure checks per step |
| Provisional credit required if investigation > 10 business days | SymPy: `credit = disputed_amount - max_liability` |
| Written acknowledgment within 1 business day | Disclosure pattern matching at `file_dispute` step |
| Internal tier system must not be exposed to customer | Pattern detection for "tier 1", "tier 2", etc. |

**Test Scenarios (pre-seeded for UI testing):**

| Dispute ID | Customer | Tier | Scenario |
|-----------|----------|------|----------|
| DISP-001 | CUST-456 | Tier 1 ($50 max) | Unauthorized debit card, reported within 2 days |
| DISP-002 | CUST-789 | Tier 2 ($500 max) | Unauthorized ACH, reported at 15 days |
| DISP-003 | CUST-012 | Tier 3 (unlimited) | Unauthorized debit, reported at 75 days (outside window) |
| DISP-004 | CUST-345 | Tier 1 ($50 max) | Error dispute — wrong amount charged |

**Try it from the UI:**
1. Start the backend and Shiny UI
2. Select customer CUST-456 from the customer selector
3. Type: "I want to dispute an unauthorized charge on my debit card"
4. The agent follows the `cs_eft_dispute` procedure through eligibility assessment, filing, and provisional credit
5. Check the Data Browser tab → `disputes` table to see the created dispute record

### Tools

Tools are async Python functions that agents call during workflow execution. Each tool:

1. Queries or mutates the database via the **repository layer**
2. Passes runtime permission and customer-binding checks
3. Routes consequential work through the durable core/action gateway
4. Logs compliance-critical actions to the **audit trail**
5. Returns a dict that the agent interprets to continue the conversation

### Database

Business/core data uses the configured `CoreStore` adapter (SQLite by default).
ADK 2.x sessions use a separate configured database. Domain/core storage includes:

- Business tables (customers, orders, accounts, transactions, fraud alerts, etc.)
- Durable case, fact, action, inbox, and handoff tables
- Audit trail table (immutable compliance log)

See [docs/database.md](docs/database.md) for the full schema reference.

### Session State

Workflow progress is tracked via session state keys:

| Key | Description |
|-----|-------------|
| `current_procedure` | ID of the active procedure |
| `current_step` | Current step being executed |
| `steps_completed` | List of completed step IDs |
| `workflow_status` | `in_progress`, `completed`, or `escalated` |
| `workflow_resolution` | How the workflow concluded |

## API Reference

The API is versioned at `/api/v1`. Legacy routes at `/api/` are maintained for backward compatibility.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/chat` | Send a message, get agent response (guardrail-filtered) |
| `WS` | `/api/v1/ws/chat` | WebSocket for streaming responses (guardrail-filtered) |
| `POST` | `/api/v1/ivr/turns` | Normalize and deduplicate a final IVR/ASR turn |
| `POST` | `/api/v1/core/refunds` | Execute an authorized idempotent refund command |
| `GET` | `/api/v1/customers?limit=&offset=` | List customers (paginated) |
| `GET` | `/api/v1/sessions?user_id=...` | List sessions for a user |
| `GET` | `/api/v1/procedures` | List all loaded procedures |
| `GET` | `/api/v1/procedures/active` | List active procedure executors with progress |
| `GET` | `/api/v1/session/{id}/state?user_id=...` | Get workflow state |
| `GET` | `/api/v1/session/{id}/procedure` | Get procedure execution progress and step history |
| `GET` | `/api/v1/tables/{name}?limit=&offset=` | Browse database table contents (paginated) |
| `GET` | `/api/v1/metrics` | Operational metrics for monitoring dashboards |
| `GET` | `/health` | Health check with version and status |

See [docs/api.md](docs/api.md) for request/response schemas and examples.

## Extending the Engine

### Adding a New Procedure

1. Create a YAML file in `procedures/` following the schema in [docs/procedures.md](docs/procedures.md)
2. If the procedure needs new tools, add them to the appropriate file in `workflow_engine/tools/`
3. Register the tools in the agent factory's `TOOL_MAP`
4. The procedure registry auto-discovers YAML files — no code changes needed for loading

### Adding a New Agent Domain

1. Create a new agent factory in `workflow_engine/agents/`
2. Define a persona, tool map, and `create_*_agent()` function
3. Register the agent as a sub-agent of the router in `router.py`
4. Update the router instruction to include routing guidance

### Adding a New Channel

1. Create a new adapter in `workflow_engine/channels/` implementing the `Channel` interface
2. Implement `receive()` (inbound normalization), `send()` (delivery), and `format_response()` (output formatting)
3. Register the adapter in the channel registry

### Adding Permissions for New Tools

1. Add new `Permission` entries in `workflow_engine/auth/models.py`
2. Map them to roles in `workflow_engine/auth/rbac.py`
3. Apply `@require_permission()` decorators or check `user.has_permission()` in tool code

## Deployment

### Development

```bash
uvicorn main:app --port 8000 --reload
```

### Production

```bash
# Docker
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Or directly with Gunicorn
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

Production checklist:
- [ ] Set `ENVIRONMENT=production`
- [ ] Set a strong `AUTH_SECRET_KEY`
- [ ] Enable `AUTH_ENABLED=true`
- [ ] Enable `RATE_LIMIT_ENABLED=true`
- [ ] Configure `CORS_ORIGINS` for your domain
- [ ] Set `LOG_FORMAT=json` for structured log aggregation
- [ ] Use PostgreSQL for the database (`DATABASE_URL=postgresql+asyncpg://...`)

## License

This project is for educational and learning purposes.
