"""FastAPI backend for the LLM-Powered Workflow Engine.

Enterprise-grade application with:
- Versioned API (v1) with backward-compatible legacy routes
- Structured error handling and logging
- Authentication middleware (JWT, optional)
- CORS, rate limiting, and correlation ID tracing
- Audit trail for compliance-critical actions
- WebSocket support for streaming responses
"""

import uuid
from contextlib import asynccontextmanager
from datetime import date
from typing import Optional

from dotenv import load_dotenv

# Load environment variables before any other imports
load_dotenv()

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService
from google.genai import types as genai_types

from workflow_engine.agent import registry, root_agent
from workflow_engine.agents.guardrails import filter_response, steer_response
from workflow_engine.audit.logger import init_audit_logger
from workflow_engine.channels.base import ChannelType, OutboundMessage
from workflow_engine.channels.http import HttpChannel, WebSocketChannel
from workflow_engine.database import close_connection, init_db, query_all, seed_all
from workflow_engine.database.repository import AuditRepository
from workflow_engine.errors import NotFoundError, ValidationError, WorkflowEngineError
from workflow_engine.logging_config import LogContext, get_logger, setup_logging
from workflow_engine.middleware.auth import AuthMiddleware
from workflow_engine.middleware.correlation import CorrelationMiddleware
from workflow_engine.middleware.error_handler import generic_error_handler, workflow_error_handler
from workflow_engine.middleware.rate_limiter import RateLimiterMiddleware
from workflow_engine.procedures.executor import ProcedureExecutorRegistry
from workflow_engine.settings import get_settings

# --- Initialize logging ---
settings = get_settings()
setup_logging(
    log_level=settings.log_level,
    log_format="text" if settings.is_dev else "json",
    log_file=settings.log_file,
)
logger = get_logger("main")

# --- Channel registry ---
http_channel = HttpChannel()
ws_channel = WebSocketChannel()

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
    "disputes",
    "escalations",
    "refunds",
    "knowledge_articles",
}


# --- Lifecycle ---


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB, seed data, and configure services on startup."""
    logger.info("Starting workflow engine (env=%s)", settings.environment.value)

    # Initialize database
    await init_db()
    await seed_all()

    # Initialize audit logger with DB persistence
    init_audit_logger(db_write_func=AuditRepository.write)
    logger.info("Audit logger initialized with DB persistence")

    logger.info(
        "Workflow engine ready — %d procedures loaded, auth=%s",
        len(registry.procedures),
        "enabled" if settings.auth_enabled else "disabled",
    )

    yield

    # Shutdown
    await close_connection()
    logger.info("Workflow engine shut down")


# --- App setup ---

app = FastAPI(
    title="LLM Workflow Engine",
    description="Enterprise-grade LLM-powered workflow engine for customer service and fraud operations.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# --- Middleware stack (order matters: outermost first) ---

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Correlation-ID"],
)

# Correlation ID tracing
app.add_middleware(CorrelationMiddleware)

# Rate limiting
app.add_middleware(RateLimiterMiddleware)

# Authentication
app.add_middleware(AuthMiddleware)

# --- Error handlers ---
app.add_exception_handler(WorkflowEngineError, workflow_error_handler)
app.add_exception_handler(Exception, generic_error_handler)

# --- Services ---

# Persistent session service backed by SQLite
session_service = DatabaseSessionService(db_url=settings.adk_session_db_url)

runner = Runner(
    agent=root_agent,
    app_name=settings.app_name,
    session_service=session_service,
)

# Procedure executor registry — tracks active procedure state machines per session
executor_registry = ProcedureExecutorRegistry()


# --- Pydantic models ---


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10000, description="User message text")
    session_id: Optional[str] = Field(default=None, description="Existing session ID to continue")
    user_id: str = Field(min_length=1, max_length=100, description="User identifier")


class ChatResponse(BaseModel):
    response: str
    session_id: str


class ProcedureInfo(BaseModel):
    id: str
    name: str
    description: str
    trigger_intents: list[str]
    version: Optional[str] = None


class ProceduresResponse(BaseModel):
    procedures: list[ProcedureInfo]
    count: int


class SessionStateResponse(BaseModel):
    session_id: str
    state: dict


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    procedures_loaded: int
    auth_enabled: bool


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


# ===========================================================================
# Versioned API (v1)
# ===========================================================================


@app.post(f"{settings.api_prefix}/chat", response_model=ChatResponse, tags=["chat"])
async def chat_v1(request: ChatRequest, req: Request) -> ChatResponse:
    """Send a message to the workflow agent and get a response.

    If no session_id is provided, a new session is created.
    """
    # Normalize inbound message via channel abstraction
    inbound = await http_channel.receive({
        "message": request.message,
        "user_id": request.user_id,
        "session_id": request.session_id,
    })

    session_id = inbound.session_id or str(uuid.uuid4())

    with LogContext(session_id=session_id, user_id=inbound.user_id):
        logger.info("Chat request from user=%s session=%s", inbound.user_id, session_id)

        # Get or create session
        session = await session_service.get_session(
            app_name=settings.app_name,
            user_id=inbound.user_id,
            session_id=session_id,
        )
        if session is None:
            session = await session_service.create_session(
                app_name=settings.app_name,
                user_id=inbound.user_id,
                session_id=session_id,
                state={
                    "customer_id": inbound.user_id,
                    "current_date": date.today().isoformat(),
                },
            )

        # Ensure customer_id and current_date are always available in session state
        if not session.state.get("customer_id"):
            session.state["customer_id"] = inbound.user_id
        session.state["current_date"] = date.today().isoformat()

        # Build user message
        user_message = genai_types.Content(
            role="user",
            parts=[genai_types.Part(text=inbound.text)],
        )

        # Run agent and collect response text from sub-agents
        response_parts: list[str] = []
        async for event in runner.run_async(
            user_id=inbound.user_id,
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
                        # Skip duplicate text from multi-turn tool call loops
                        text = part.text.strip()
                        if text and (not response_parts or text != response_parts[-1].strip()):
                            response_parts.append(part.text)

        response_text = "\n\n".join(response_parts) if response_parts else ""

        # Fallback when the model produces no output (e.g., STOP with no content)
        if not response_text.strip():
            logger.warning("Empty response from agent for session=%s", session_id)
            response_text = (
                "I'm sorry, I wasn't able to process your request. "
                "Could you please rephrase or provide more details?"
            )

        # Apply guardrails — layered pipeline: pattern rails → reasoning → compliance → steering
        # Extract procedure context from session state for reasoning verification
        active_procedure_id = session.state.get("current_procedure") if session.state else None
        active_step = session.state.get("current_step") if session.state else None
        session_state_dict = dict(session.state) if session.state else {}

        # Look up the procedure definition for rule extraction
        procedure_def = None
        if active_procedure_id and active_procedure_id in registry.procedures:
            procedure_def = registry.procedures[active_procedure_id]

        response_text, violations, verification = await steer_response(
            text=response_text,
            session_state=session_state_dict,
            procedure_id=active_procedure_id,
            current_step=active_step,
            procedure_def=procedure_def,
            generate_fn=None,  # No rewrite loop for now — requires LLM callback
            max_iterations=2,
        )
        if violations:
            logger.warning(
                "Guardrail violations filtered from response (session=%s): %s",
                session_id,
                [v.rule for v in violations],
            )
        if verification and not verification.is_valid and verification.verdict != "NOT_APPLICABLE":
            logger.warning(
                "Reasoning verification result (session=%s): verdict=%s, findings=%d",
                session_id,
                verification.verdict,
                len(verification.findings),
            )

        logger.info("Chat response generated (len=%d)", len(response_text))

        return ChatResponse(response=response_text, session_id=session_id)


@app.get(f"{settings.api_prefix}/procedures", response_model=ProceduresResponse, tags=["procedures"])
async def list_procedures_v1() -> ProceduresResponse:
    """List all available procedures with their metadata."""
    procedures = []
    for proc_id, proc in registry.procedures.items():
        procedures.append(
            ProcedureInfo(
                id=proc_id,
                name=proc.get("name", ""),
                description=proc.get("description", ""),
                trigger_intents=proc.get("trigger_intents", []),
                version=proc.get("version"),
            )
        )
    return ProceduresResponse(procedures=procedures, count=len(procedures))


@app.get(
    f"{settings.api_prefix}/session/{{session_id}}/state",
    response_model=SessionStateResponse,
    tags=["sessions"],
)
async def get_session_state_v1(session_id: str, user_id: str) -> SessionStateResponse:
    """Get the workflow state for a given session."""
    session = await session_service.get_session(
        app_name=settings.app_name,
        user_id=user_id,
        session_id=session_id,
    )
    if session is None:
        raise NotFoundError("Session", session_id)

    raw_state = dict(session.state) if session.state else {}
    workflow_state = {k: v for k, v in raw_state.items() if k in _WORKFLOW_STATE_KEYS}
    return SessionStateResponse(session_id=session_id, state=workflow_state)


@app.get(f"{settings.api_prefix}/customers", tags=["customers"])
async def list_customers_v1(limit: int = 100, offset: int = 0) -> dict:
    """Return all customers for the UI customer selector."""
    rows = await query_all(
        "SELECT customer_id, name FROM customers LIMIT ? OFFSET ?",
        (limit, offset),
    )
    return {"customers": rows, "count": len(rows), "limit": limit, "offset": offset}


@app.get(f"{settings.api_prefix}/sessions", tags=["sessions"])
async def list_sessions_v1(user_id: str) -> dict:
    """List all sessions for a user."""
    resp = await session_service.list_sessions(
        app_name=settings.app_name,
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
    return {"sessions": result, "count": len(result)}


@app.get(f"{settings.api_prefix}/tables/{{table_name}}", tags=["data"])
async def get_table_data_v1(table_name: str, limit: int = 100, offset: int = 0) -> dict:
    """Get all rows from an allowed table for the data browser."""
    if table_name not in _ALLOWED_TABLES:
        raise ValidationError(
            f"Table '{table_name}' is not browsable",
            field="table_name",
            details={"allowed": sorted(_ALLOWED_TABLES)},
        )
    rows = await query_all(
        f"SELECT * FROM {table_name} LIMIT ? OFFSET ?",  # noqa: S608 — table_name is allowlisted
        (limit, offset),
    )
    return {"table": table_name, "rows": rows, "count": len(rows), "limit": limit, "offset": offset}


# --- WebSocket endpoint for streaming responses ---


@app.websocket(f"{settings.api_prefix}/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket endpoint for real-time streaming agent responses."""
    await websocket.accept()
    logger.info("WebSocket connection established")

    try:
        while True:
            data = await websocket.receive_json()
            inbound = await ws_channel.receive(data)

            session_id = inbound.session_id or str(uuid.uuid4())
            user_id = inbound.user_id

            with LogContext(session_id=session_id, user_id=user_id):
                # Get or create session
                session = await session_service.get_session(
                    app_name=settings.app_name,
                    user_id=user_id,
                    session_id=session_id,
                )
                if session is None:
                    session = await session_service.create_session(
                        app_name=settings.app_name,
                        user_id=user_id,
                        session_id=session_id,
                        state={
                            "customer_id": user_id,
                            "current_date": date.today().isoformat(),
                        },
                    )

                if not session.state.get("customer_id"):
                    session.state["customer_id"] = user_id
                session.state["current_date"] = date.today().isoformat()

                user_message = genai_types.Content(
                    role="user",
                    parts=[genai_types.Part(text=inbound.text)],
                )

                # Stream responses as they arrive
                async for event in runner.run_async(
                    user_id=user_id,
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
                                # Apply guardrails before sending to client
                                filtered_text, violations = filter_response(part.text)
                                if violations:
                                    logger.warning(
                                        "Guardrail violations filtered from WS stream (session=%s): %s",
                                        session_id,
                                        [v.rule for v in violations],
                                    )
                                msg = OutboundMessage(
                                    channel=ChannelType.WEBSOCKET,
                                    user_id=user_id,
                                    session_id=session_id,
                                    text=filtered_text,
                                )
                                frame = await ws_channel.format_response(msg)
                                await websocket.send_json(frame)

                # Send completion marker
                await websocket.send_json({
                    "type": "stream_end",
                    "session_id": session_id,
                })

    except WebSocketDisconnect:
        logger.info("WebSocket connection closed")


@app.get(f"{settings.api_prefix}/procedures/active", tags=["procedures"])
async def list_active_procedures_v1() -> dict:
    """List all active procedure executors with their progress."""
    active = executor_registry.list_active()
    return {"active_procedures": active, "count": len(active)}


@app.get(f"{settings.api_prefix}/session/{{session_id}}/procedure", tags=["procedures"])
async def get_session_procedure_v1(session_id: str) -> dict:
    """Get the procedure execution progress for a session."""
    executor = executor_registry.get(session_id)
    if executor is None:
        return {"session_id": session_id, "procedure": None, "message": "No active procedure for this session."}
    return {
        "session_id": session_id,
        "procedure": executor.get_progress(),
        "step_history": executor.get_step_history(),
    }


# --- Metrics endpoint ---


@app.get(f"{settings.api_prefix}/metrics", tags=["system"])
async def metrics_v1() -> dict:
    """Basic operational metrics for monitoring dashboards."""
    active_procedures = executor_registry.list_active()
    return {
        "procedures_loaded": len(registry.procedures),
        "active_procedures": len(active_procedures),
        "auth_enabled": settings.auth_enabled,
        "rate_limit_enabled": settings.rate_limit_enabled,
        "environment": settings.environment.value,
    }


# ===========================================================================
# Legacy API routes (backward compatibility with v0.2.0 clients)
# ===========================================================================


@app.post("/api/chat", response_model=ChatResponse, tags=["legacy"], include_in_schema=False)
async def chat_legacy(request: ChatRequest, req: Request) -> ChatResponse:
    """Legacy chat endpoint — delegates to v1."""
    return await chat_v1(request, req)


@app.get("/api/procedures", response_model=ProceduresResponse, tags=["legacy"], include_in_schema=False)
async def list_procedures_legacy() -> ProceduresResponse:
    return await list_procedures_v1()


@app.get("/api/session/{session_id}/state", response_model=SessionStateResponse, tags=["legacy"], include_in_schema=False)
async def get_session_state_legacy(session_id: str, user_id: str) -> SessionStateResponse:
    return await get_session_state_v1(session_id, user_id)


@app.get("/api/customers", tags=["legacy"], include_in_schema=False)
async def list_customers_legacy() -> dict:
    return await list_customers_v1()


@app.get("/api/tables/{table_name}", tags=["legacy"], include_in_schema=False)
async def get_table_data_legacy(table_name: str) -> dict:
    return await get_table_data_v1(table_name)


@app.get("/api/sessions", tags=["legacy"], include_in_schema=False)
async def list_sessions_legacy(user_id: str) -> dict:
    return await list_sessions_v1(user_id)


# ===========================================================================
# Health check (unversioned)
# ===========================================================================


@app.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(
        status="ok",
        version="1.0.0",
        environment=settings.environment.value,
        procedures_loaded=len(registry.procedures),
        auth_enabled=settings.auth_enabled,
    )
