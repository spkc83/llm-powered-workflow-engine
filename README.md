# LLM-Powered Workflow Engine

An enterprise-grade, procedure-driven workflow engine built on [Google ADK](https://google.github.io/adk-docs/) (Agent Development Kit) that uses LLM agents to execute structured business processes. Designed for customer service, fraud operations, and claims workflows at financial institutions.

Agents follow YAML-defined step-by-step procedures while maintaining natural conversational interaction, with runtime enforcement via a stateful procedure executor.

## Architecture

```
┌──────────────────────┐          ┌──────────────────────────────────┐
│  Shiny App (UI)      │  httpx   │  FastAPI Backend                 │
│  Port 8001           │────────→ │  Port 8000                       │
│                      │          │                                  │
│  - Chat panel        │          │  API (v1)                        │
│  - Customer selector │          │  ├── /api/v1/chat (REST + WS)    │
│  - Session history   │          │  ├── /api/v1/customers           │
│  - Test scenarios    │          │  ├── /api/v1/sessions            │
│  - Workflow state    │          │  ├── /api/v1/procedures          │
│  - Data browser tab  │          │  ├── /api/v1/session/{id}/state  │
│                      │          │  ├── /api/v1/tables/{name}       │
└──────────────────────┘          │  ├── /api/v1/ws/chat (WebSocket) │
                                  │  └── /health                     │
                                  │                                  │
                                  │  Middleware Stack                 │
                                  │  ├── CORS                        │
                                  │  ├── Correlation ID tracing      │
                                  │  ├── Rate limiting               │
                                  │  ├── JWT Authentication          │
                                  │  └── Structured error handling   │
                                  └───────────┬────────────────────┘
                                              │
                                  ┌───────────▼───────────┐
                                  │  Database              │
                                  │  SQLite (dev) /        │
                                  │  PostgreSQL (prod)     │
                                  │                        │
                                  │  - Business data       │
                                  │  - ADK session tables  │
                                  │  - Audit trail         │
                                  └────────────────────────┘
```

### Agent Hierarchy

```
router_agent (configurable — default: Gemini 2.5 Flash)
├── customer_service_agent — orders, refunds, returns, complaints
│   └── Tools: lookup_order, search_orders, get_customer_profile,
│             issue_refund, update_case_status, escalate_to_supervisor,
│             add_case_note, get_knowledge_article
├── fraud_ops_agent — alert triage, investigation, account actions
│   └── Tools: get_fraud_alert, get_account_transactions,
│             check_device_fingerprint, flag_account,
│             submit_sar, close_alert, escalate_to_supervisor,
│             add_case_note
└── general_agent — greetings, general questions, fallback
```

The **router agent** examines user intent and delegates to the appropriate specialist. Each specialist agent receives procedure-derived instructions that guide it through a structured workflow while maintaining natural conversation.

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
├── requirements.txt                # Python dependencies
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
│   └── fraud_ops_alert_triage.yaml
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
│   │   └── guardrails.py           # Output filtering, tool arg validation
│   │
│   ├── auth/                       # Authentication & authorization
│   │   ├── models.py               # Role, Permission, UserContext models
│   │   ├── rbac.py                 # Role-based access control mappings
│   │   └── jwt_handler.py          # JWT token creation and verification
│   │
│   ├── audit/                      # Compliance audit trail
│   │   └── logger.py               # Immutable audit logging with DB persistence
│   │
│   ├── channels/                   # Omni-channel abstraction
│   │   ├── base.py                 # Channel interface, InboundMessage, OutboundMessage
│   │   └── http.py                 # HTTP REST and WebSocket adapters
│   │
│   ├── middleware/                  # FastAPI middleware stack
│   │   ├── auth.py                 # JWT authentication middleware
│   │   ├── correlation.py          # Request correlation ID tracing
│   │   ├── error_handler.py        # Structured error responses
│   │   └── rate_limiter.py         # In-memory rate limiting
│   │
│   ├── tools/                      # Tool implementations (async, SQLite-backed)
│   │   ├── crm_tools.py            # lookup_order, search_orders, get_customer_profile, issue_refund, update_case_status
│   │   ├── fraud_tools.py          # get_fraud_alert, get_account_transactions, check_device_fingerprint, flag_account, submit_sar, close_alert
│   │   └── common_tools.py         # escalate_to_supervisor, add_case_note, get_knowledge_article
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
│   ├── api.md                      # API reference
│   ├── database.md                 # Schema reference
│   └── procedures.md               # Procedure authoring guide
│
└── tests/                          # Test suite (281 tests)
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
    ├── test_guardrails.py          # Output filtering, tool arg validation
    ├── test_channels.py            # Channel abstraction, HTTP/WS adapters
    └── test_audit.py               # Audit trail logging
```

## Configuration

All configuration is centralized via [Pydantic BaseSettings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/). Settings are loaded from environment variables or `.env` files with full validation and type coercion.

See `.env.example` for the complete reference. Key settings:

| Variable | Description | Default |
|----------|-------------|---------|
| `ENVIRONMENT` | Runtime environment (`dev`, `staging`, `production`) | `dev` |
| `GOOGLE_API_KEY` | Google AI API key (required) | — |
| `LLM_MODEL` | Model name for all agents | `gemini-2.5-flash` |
| `DATABASE_URL` | Database connection URL | `sqlite+aiosqlite:///data/workflow.db` |
| `API_PREFIX` | API route prefix | `/api/v1` |
| `AUTH_ENABLED` | Enable JWT authentication | `false` |
| `AUTH_SECRET_KEY` | JWT signing secret | dev default |
| `RATE_LIMIT_ENABLED` | Enable request rate limiting | `false` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `LOG_FORMAT` | Log format (`text` or `json`) | `text` (dev) / `json` (prod) |
| `CORS_ORIGINS` | Allowed CORS origins | `["http://localhost:8001"]` |

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

Every compliance-critical action is recorded in an immutable audit trail:

- Refunds issued, accounts flagged, SARs submitted
- Procedure starts, step transitions, completions
- Full context: who, what, when, session, procedure, before/after state

### Channels (Omni-Channel)

The channel abstraction layer normalizes messages from different communication sources:

- **HTTP REST** — standard request/response chat
- **WebSocket** — real-time streaming responses
- **Extensible** — add SMS, email, WhatsApp, IVR adapters by implementing the `Channel` interface

### Agent Guardrails

Output filtering is wired into both the REST and WebSocket chat endpoints. Every agent response is passed through `filter_response()` before reaching the user. This prevents agents from:

- Leaking internal data (step IDs, SQL queries, credentials)
- Making unauthorized promises or guarantees
- Providing unauthorized financial/legal advice

Tool argument validation catches:

- Negative amounts, malformed IDs
- Oversized inputs (prompt injection prevention)

### Tools

Tools are async Python functions that agents call during workflow execution. Each tool:

1. Queries or mutates the database via the **repository layer**
2. Logs compliance-critical actions to the **audit trail**
3. Stores relevant results in `tool_context.state` for use in later steps
3. Returns a dict that the agent interprets to continue the conversation

### Database

Business data is stored in SQLite (dev) or PostgreSQL (production). The database includes:

- Business tables (customers, orders, accounts, transactions, fraud alerts, etc.)
- ADK session tables (conversation history)
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
