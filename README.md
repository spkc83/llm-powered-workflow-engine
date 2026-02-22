# LLM-Powered Workflow Engine

A procedure-driven workflow engine built on [Google ADK](https://google.github.io/adk-docs/) (Agent Development Kit) that uses LLM agents to execute structured business processes. Agents follow YAML-defined step-by-step procedures while maintaining natural conversational interaction.

## Architecture

```
┌──────────────────────┐          ┌──────────────────────┐
│  Shiny App (UI)      │  httpx   │  FastAPI Backend      │
│  Port 8001           │────────→ │  Port 8000            │
│                      │          │                       │
│  - Chat panel        │          │  - /api/chat          │
│  - Customer selector │          │  - /api/customers     │
│  - Session history   │          │  - /api/sessions      │
│  - Test scenarios    │          │  - /api/procedures    │
│  - Workflow state    │          │  - /api/session/{id}  │
│  - Data browser tab  │          │  - /api/tables/{name} │
│                      │          │  - /health            │
└──────────────────────┘          └───────────┬───────────┘
                                              │
                                  ┌───────────▼───────────┐
                                  │  SQLite Database       │
                                  │  data/workflow.db      │
                                  │                        │
                                  │  - Business data       │
                                  │  - ADK session tables  │
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

# Configure your API key and model settings
echo 'GOOGLE_API_KEY="your-key-here"' > .env
echo 'GOOGLE_GENAI_USE_VERTEXAI=FALSE' >> .env

# Optional: customize LLM model and parameters
echo 'LLM_MODEL=gemini-2.5-flash' >> .env
echo 'LLM_TEMPERATURE=0.7' >> .env
# echo 'LLM_TOP_P=0.9' >> .env
# echo 'LLM_TOP_K=40' >> .env
# echo 'LLM_MAX_OUTPUT_TOKENS=8192' >> .env
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
├── main.py                         # FastAPI backend — API endpoints, session service, runner
├── app_ui.py                       # Shiny for Python chat UI
├── requirements.txt                # Python dependencies
├── .env                            # API keys (not committed)
│
├── procedures/                     # YAML workflow definitions
│   ├── customer_service_refund.yaml
│   ├── customer_service_complaint.yaml
│   └── fraud_ops_alert_triage.yaml
│
├── workflow_engine/                # Core engine package
│   ├── config.py                   # LLM model config — google.genai Client, model name, generation params
│   ├── agent.py                    # ADK entry point — registry + root_agent
│   │
│   ├── agents/                     # Agent factories
│   │   ├── router.py               # Router agent + general agent
│   │   ├── customer_service.py     # Customer service agent factory
│   │   └── fraud_ops.py            # Fraud operations agent factory
│   │
│   ├── tools/                      # Tool implementations (async, SQLite-backed)
│   │   ├── crm_tools.py            # lookup_order, search_orders, get_customer_profile, issue_refund, update_case_status
│   │   ├── fraud_tools.py          # get_fraud_alert, get_account_transactions, check_device_fingerprint, flag_account, submit_sar, close_alert
│   │   └── common_tools.py         # escalate_to_supervisor, add_case_note, get_knowledge_article
│   │
│   ├── database/                   # SQLite persistence layer
│   │   ├── __main__.py             # Standalone DB init: python -m workflow_engine.database [--reset]
│   │   ├── db.py                   # Schema, connection helpers, query_one/query_all/execute
│   │   └── seed.py                 # Seed data (customers, orders, alerts, etc.)
│   │
│   ├── procedures/                 # Procedure loading and registry
│   │   ├── loader.py               # YAML parser, validator, instruction builder
│   │   └── registry.py             # Procedure registry with intent mapping
│   │
│   └── state/                      # Workflow state tracking
│       └── workflow_state.py       # initialize, step tracking, completion, escalation
│
├── data/                           # SQLite database (created at runtime)
│   └── workflow.db
│
└── tests/                          # Test suite (196 tests)
    ├── test_database.py            # DB init, seed, query helpers
    ├── test_mock_tools.py          # All tool functions (async, uses temp DB)
    ├── test_workflow_state.py      # State tracking logic
    ├── test_procedure_loader.py    # YAML loading and validation
    ├── test_procedure_registry.py  # Registry and intent mapping
    ├── test_agent_factory.py       # Agent creation
    ├── test_agent_integration.py   # Integration tests
    └── test_api.py                 # FastAPI endpoint tests
```

## Configuration

All agents use a shared `google.genai.Client` configured from environment variables. Settings go in `.env` or the shell environment.

| Variable | Description | Default |
|----------|-------------|---------|
| `GOOGLE_API_KEY` | Google AI API key (required) | — |
| `GOOGLE_GENAI_USE_VERTEXAI` | Set to `TRUE` to use Vertex AI backend | `FALSE` |
| `LLM_MODEL` | Model name for all agents | `gemini-2.5-flash` |
| `LLM_TEMPERATURE` | Sampling temperature (0.0–2.0) | model default |
| `LLM_TOP_P` | Top-p nucleus sampling | model default |
| `LLM_TOP_K` | Top-k sampling | model default |
| `LLM_MAX_OUTPUT_TOKENS` | Maximum output tokens | model default |

The configuration is centralized in `workflow_engine/config.py`. Each agent receives a `Gemini` model instance backed by the shared Client, so changing `LLM_MODEL` or generation parameters in `.env` applies to all agents.

## Key Concepts

### Procedures

Procedures are YAML files that define structured workflows as a sequence of steps. Each step has:

- **`id`** — unique identifier for the step
- **`instruction`** — natural language guidance for the agent
- **`action`** — step type: `collect_info`, `tool_call`, `evaluate`, or `inform`
- **Branching** — `next_step`, `on_success`/`on_failure`, `conditions`, or `options`

The procedure loader transforms YAML steps into agent instructions, and the agent follows them conversationally while using the appropriate tools at each step.

See [docs/procedures.md](docs/procedures.md) for the full procedure authoring guide.

### Tools

Tools are async Python functions that agents call during workflow execution. Each tool:

1. Queries or mutates the SQLite database
2. Stores relevant results in `tool_context.state` for use in later steps
3. Returns a dict that the agent interprets to continue the conversation

### Database

All business data is stored in SQLite (`data/workflow.db`). The database is initialized and seeded automatically on application startup. ADK's `DatabaseSessionService` stores conversation sessions in the same database.

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

State is accessible via the `GET /api/session/{session_id}/state` endpoint.

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/chat` | Send a message, get agent response |
| `GET` | `/api/customers` | List all customers (for UI selector) |
| `GET` | `/api/sessions?user_id=...` | List all sessions for a user |
| `GET` | `/api/procedures` | List all loaded procedures |
| `GET` | `/api/session/{id}/state?user_id=...` | Get workflow state for a session |
| `GET` | `/api/tables/{name}` | Browse database table contents |
| `GET` | `/health` | Health check |

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

## License

This project is for educational and learning purposes.
