"""FastAPI backend for the LLM-Powered Workflow Engine."""

import uuid
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Load environment variables first
load_dotenv()

from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService
from google.genai import types as genai_types

from workflow_engine.agent import registry, root_agent
from workflow_engine.database import init_db, query_all, seed_all

# --- Allowed tables for the data browser ---

_ALLOWED_TABLES = {
    "customers",
    "orders",
    "order_items",
    "accounts",
    "transactions",
    "fraud_alerts",
    "devices",
    "login_history",
    "risk_indicators",
    "cases",
    "case_notes",
    "escalations",
    "refunds",
    "knowledge_articles",
}


# --- Lifecycle ---


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB and seed data on startup."""
    await init_db()
    await seed_all()
    yield


# --- App setup ---

app = FastAPI(
    title="LLM Workflow Engine",
    description="LLM-powered workflow engine using Google ADK with procedure-driven agents.",
    version="0.2.0",
    lifespan=lifespan,
)

# Persistent session service backed by SQLite
session_service = DatabaseSessionService(db_url="sqlite:///data/workflow.db")

runner = Runner(
    agent=root_agent,
    app_name="workflow_engine",
    session_service=session_service,
)

# --- Pydantic models ---


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    user_id: str


class ChatResponse(BaseModel):
    response: str
    session_id: str


class ProcedureInfo(BaseModel):
    id: str
    name: str
    description: str
    trigger_intents: list[str]


class ProceduresResponse(BaseModel):
    procedures: list[ProcedureInfo]


class SessionStateResponse(BaseModel):
    session_id: str
    state: dict


# --- Workflow state keys to expose ---

_WORKFLOW_STATE_KEYS = {
    "current_procedure",
    "current_procedure_name",
    "current_step",
    "steps_completed",
    "workflow_status",
    "workflow_started_at",
    "workflow_resolution",
    "workflow_completed_at",
    "escalation_reason",
    "escalated_at",
}


# --- Endpoints ---


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Send a message to the workflow agent and get a response.

    If no session_id is provided, a new session is created.
    """
    session_id = request.session_id or str(uuid.uuid4())

    # Get or create session
    session = await session_service.get_session(
        app_name="workflow_engine",
        user_id=request.user_id,
        session_id=session_id,
    )
    if session is None:
        session = await session_service.create_session(
            app_name="workflow_engine",
            user_id=request.user_id,
            session_id=session_id,
        )

    # Build user message
    user_message = genai_types.Content(
        role="user",
        parts=[genai_types.Part(text=request.message)],
    )

    # Run agent and collect response text from sub-agents.
    # In ADK's multi-agent setup, the sub-agent's substantive responses
    # (order lookups, refund confirmations, etc.) are in events that also
    # contain function_call parts, so is_final_response() returns False
    # for all of them.  We collect all text from non-router agent events
    # to capture the full workflow conversation.
    response_parts = []
    async for event in runner.run_async(
        user_id=request.user_id,
        session_id=session_id,
        new_message=user_message,
    ):
        if (
            event.author != "router_agent"
            and event.content
            and event.content.parts
        ):
            for part in event.content.parts:
                if part.text:
                    response_parts.append(part.text)

    response_text = "\n\n".join(response_parts) if response_parts else ""

    return ChatResponse(response=response_text, session_id=session_id)


@app.get("/api/procedures", response_model=ProceduresResponse)
async def list_procedures() -> ProceduresResponse:
    """List all available procedures with their metadata."""
    procedures = []
    for proc_id, proc in registry.procedures.items():
        procedures.append(
            ProcedureInfo(
                id=proc_id,
                name=proc.get("name", ""),
                description=proc.get("description", ""),
                trigger_intents=proc.get("trigger_intents", []),
            )
        )
    return ProceduresResponse(procedures=procedures)


@app.get("/api/session/{session_id}/state", response_model=SessionStateResponse)
async def get_session_state(session_id: str, user_id: str) -> SessionStateResponse:
    """Get the workflow state for a given session.

    Returns workflow-related state keys: current procedure, step, status, etc.
    """
    session = await session_service.get_session(
        app_name="workflow_engine",
        user_id=user_id,
        session_id=session_id,
    )
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    # Filter to workflow-relevant keys only
    raw_state = dict(session.state) if session.state else {}
    workflow_state = {k: v for k, v in raw_state.items() if k in _WORKFLOW_STATE_KEYS}

    return SessionStateResponse(session_id=session_id, state=workflow_state)


@app.get("/api/customers")
async def list_customers() -> dict:
    """Return all customers for the UI customer selector."""
    rows = await query_all("SELECT customer_id, name FROM customers")
    return {"customers": rows}


@app.get("/api/tables/{table_name}")
async def get_table_data(table_name: str) -> dict:
    """Get all rows from an allowed table for the data browser."""
    if table_name not in _ALLOWED_TABLES:
        raise HTTPException(status_code=400, detail=f"Table '{table_name}' is not allowed")
    rows = await query_all(f"SELECT * FROM {table_name}")  # noqa: S608 — table_name is allowlisted
    return {"table": table_name, "rows": rows, "count": len(rows)}


@app.get("/api/sessions")
async def list_sessions(user_id: str) -> dict:
    """List all sessions for a user.

    Returns session IDs and basic metadata so the UI can offer a session
    switcher.  Ordered newest-first by looking at the ADK session store.
    """
    resp = await session_service.list_sessions(
        app_name="workflow_engine",
        user_id=user_id,
    )
    result = []
    for s in (resp.sessions if resp and resp.sessions else []):
        state = dict(s.state) if s.state else {}
        result.append({
            "session_id": s.id,
            "procedure": state.get("current_procedure_name", ""),
            "status": state.get("workflow_status", ""),
        })
    return {"sessions": result}


@app.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    return {"status": "ok", "procedures_loaded": len(registry.procedures)}
