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
import hashlib
from contextlib import asynccontextmanager
from datetime import date
from typing import Any, Literal, Optional

from dotenv import load_dotenv

# Load environment variables before any other imports
load_dotenv()

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError as PydanticValidationError

from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService
from google.genai import types as genai_types

from workflow_engine.agent import registry, root_agent
from workflow_engine import __version__
from workflow_engine.auth.context import resolve_customer_context, session_owner_id
from workflow_engine.auth.jwt_handler import decode_access_token
from workflow_engine.auth.models import Role, UserContext
from workflow_engine.auth.rbac import build_user_context
from workflow_engine.agents.guardrails import steer_response
from workflow_engine.audit.logger import init_audit_logger
from workflow_engine.channels.http import HttpChannel, WebSocketChannel
from workflow_engine.database import (
    close_connection,
    configure_db_path,
    init_db,
    query_all,
    seed_all,
)
from workflow_engine.database.repository import AuditRepository
from workflow_engine.database.repository import OrderRepository
from workflow_engine.errors import NotFoundError, ValidationError, WorkflowEngineError
from workflow_engine.errors import AuthorizationError
from workflow_engine.logging_config import LogContext, get_logger, setup_logging
from workflow_engine.middleware.auth import AuthMiddleware, get_current_user
from workflow_engine.middleware.correlation import CorrelationMiddleware
from workflow_engine.middleware.error_handler import generic_error_handler, workflow_error_handler
from workflow_engine.middleware.rate_limiter import RateLimiterMiddleware
from workflow_engine.procedures.executor import ProcedureExecutorRegistry
from workflow_engine.settings import get_settings
from workflow_engine.core import CaseKernel, create_core_store
from workflow_engine.core.adapter_loading import load_factory
from workflow_engine.core.connectors import DatabaseRefundConnector
from workflow_engine.core.domains import OrderSnapshot, RefundDecisionService
from workflow_engine.core.gateway import ActionConnector, ActionGateway
from workflow_engine.core.service import CoreEngine
from workflow_engine.core.policy import (
    PolicyLifecycle,
    PolicyPackage,
    PolicyRegistry,
    PolicySigner,
)
from workflow_engine.core.policy_store import PolicyService, create_policy_repository
from workflow_engine.core.action_service import (
    ACTION_PERMISSIONS,
    ActionPayload,
    AuthoritativeResourceRef,
    ConsequentialActionRequest,
    ConsequentialActionService,
)
from workflow_engine.actions import (
    ActionBridge,
    ActionConfirmationContext,
    ActionIntent,
    TrustedActionContext,
)
from workflow_engine.core.action_specs import ACTION_SPECIFICATIONS
from workflow_engine.core.workers import ActionDeliveryWorker, ReconciliationWorker
from workflow_engine.core.kernel import (
    ActionProposalStatus,
    ActionRecord,
    ActionStatus,
    OutboxStatus,
)
from workflow_engine.core.jurisdiction import JurisdictionGuard, load_jurisdiction_profile
from workflow_engine.auth.models import Permission
from workflow_engine.conversation.runtime import ChannelKind, ConversationRuntime, MessageEnvelope
from workflow_engine.conversation.contracts import RiskLevel
from workflow_engine.conversation.service import (
    ConversationService,
    GeneratedTurn,
    TurnContext,
    TurnResult,
)
from workflow_engine.conversation.runtime import HandoffStatus
from workflow_engine.channels.ivr import IvrAdapter
from workflow_engine.integrations.contracts import (
    HandoffRequest,
    ProviderReceipt,
    SttRequest,
    SttResult,
    TelephonyEvent,
    TtsRequest,
    TtsResult,
)
from workflow_engine.integrations.sandbox import (
    DisabledActionConnector,
    LocalChatAdapter,
    LocalTelephonyAdapter,
    SandboxScenario,
    SQLiteDeliveryReceiptStore,
    SQLiteHandoffQueueAdapter,
    SQLiteSandboxActionConnector,
    StubSpeechToTextAdapter,
    StubTextToSpeechAdapter,
)
from workflow_engine.integrations.loading import (
    ProviderBundle,
    load_action_connector_registry,
    validate_provider_bundle,
)
from workflow_engine.integrations.registry import (
    ActionConnectorRegistry,
    ActionRegistryConfig,
    SQLiteActionBinding,
)
from workflow_engine.integrations.resources import (
    ChainedResourceProvider,
    ReferenceDataResourceProvider,
)
from workflow_engine.mcp import create_action_mcp_server
from workflow_engine.settings import UpstreamMode

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
    configure_db_path(settings.reference_data_sqlite_path)
    await init_db()
    if settings.effective_seed_reference_data:
        await seed_all()
    await core_store.initialize()
    await policy_repository.initialize()
    await sandbox_action_connector.initialize()
    if provider_bundle is not None:
        await provider_bundle.initialize()
    else:
        initialize_handoff = getattr(handoff_provider, "initialize", None)
        if initialize_handoff is not None:
            await initialize_handoff()
        await delivery_receipts.initialize()
    for package in bootstrap_policies:
        if await policy_repository.get(package.package_id) is None:
            await policy_repository.save(package)
    policy_registry.clear()
    await policy_service.hydrate()

    # Initialize audit logger with DB persistence
    init_audit_logger(db_write_func=AuditRepository.write)
    logger.info("Audit logger initialized with DB persistence")

    logger.info(
        "Workflow engine ready — %d procedures loaded, auth=%s",
        len(registry.procedures),
        "enabled" if settings.auth_enabled else "disabled",
    )

    async with action_mcp_server.session_manager.run():
        yield

    # Shutdown
    await close_connection()
    logger.info("Workflow engine shut down")


# --- App setup ---

app = FastAPI(
    title="LLM Workflow Engine",
    description="Enterprise-grade LLM-powered workflow engine for customer service and fraud operations.",
    version=__version__,
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

# Authoritative core action path. ADK/model code cannot write action records.
_core_scheme = settings.database_url.split(":", 1)[0].split("+", 1)[0]
_core_adapters = {}
if settings.core_store_adapter_factory:
    _core_adapters[_core_scheme] = load_factory(settings.core_store_adapter_factory)
core_store = create_core_store(settings.database_url, adapters=_core_adapters)
core_kernel = CaseKernel(core_store)
policy_signer = PolicySigner(
    settings.policy_signing_key.encode(),
    key_id=settings.policy_signing_key_id,
    verification_keys={
        key_id: value.encode()
        for key_id, value in settings.policy_verification_keys.items()
    },
)
active_refund_policy = policy_signer.activate(
    policy_signer.approve(
        PolicyPackage(
            package_id=f"refund@1.0.0:{settings.jurisdiction_profile}",
            procedure_id="cs_refund",
            version="1.0.0",
            jurisdiction=settings.jurisdiction_profile,
            author=settings.policy_author,
            rules={
                "refund_window_days": 30,
                "requires_explicit_consent": True,
                "allowed_actions": [
                    "issue_refund",
                    "issue_store_credit",
                    "update_case_status",
                    "escalate_to_supervisor",
                    "add_case_note",
                ],
            },
        ),
        approver=settings.policy_approver,
    )
)
active_reg_e_policy = policy_signer.activate(
    policy_signer.approve(
        PolicyPackage(
            package_id=f"reg-e@1.0.0:{settings.jurisdiction_profile}",
            procedure_id="cs_eft_dispute",
            version="1.0.0",
            jurisdiction=settings.jurisdiction_profile,
            author=settings.policy_author,
            rules={
                "allowed_actions": [
                    "file_eft_dispute",
                    "issue_provisional_credit",
                    "escalate_to_supervisor",
                    "add_case_note",
                ]
            },
        ),
        approver=settings.policy_approver,
    )
)
active_fraud_policy = policy_signer.activate(
    policy_signer.approve(
        PolicyPackage(
            package_id=f"fraud@1.0.0:{settings.jurisdiction_profile}",
            procedure_id="fraud_alert_triage",
            version="1.0.0",
            jurisdiction=settings.jurisdiction_profile,
            author=settings.policy_author,
            rules={
                "allowed_actions": [
                    "flag_account",
                    "submit_sar",
                    "close_alert",
                    "escalate_to_supervisor",
                    "add_case_note",
                ]
            },
        ),
        approver=settings.policy_approver,
    )
)
policy_registry = PolicyRegistry(policy_signer)
for _package in (active_refund_policy, active_reg_e_policy, active_fraud_policy):
    policy_registry.load(_package)
bootstrap_policies = (active_refund_policy, active_reg_e_policy, active_fraud_policy)
_policy_url = settings.effective_policy_database_url
_policy_scheme = _policy_url.split(":", 1)[0].split("+", 1)[0]
_policy_adapters = {}
if settings.policy_repository_adapter_factory:
    _policy_adapters[_policy_scheme] = load_factory(
        settings.policy_repository_adapter_factory
    )
policy_repository = create_policy_repository(_policy_url, adapters=_policy_adapters)
policy_service = PolicyService(policy_repository, policy_signer, policy_registry)

sandbox_action_connector = SQLiteSandboxActionConnector(settings.sandbox_sqlite_path)
default_action_connector: ActionConnector
provider_bundle: ProviderBundle | None = None
if settings.effective_upstream_mode is UpstreamMode.PROVIDER:
    provider_factory = load_factory(settings.provider_bundle_factory or "")
    provider_bundle = validate_provider_bundle(provider_factory(settings))
    stt_provider = provider_bundle.stt
    tts_provider = provider_bundle.tts
    telephony_provider = provider_bundle.telephony
    chat_provider = provider_bundle.chat
    handoff_provider = provider_bundle.handoff
    default_action_connector = provider_bundle.action
    authoritative_resources = provider_bundle.resources
    delivery_receipts = SQLiteDeliveryReceiptStore(settings.sandbox_sqlite_path)
elif settings.effective_upstream_mode is UpstreamMode.SANDBOX:
    default_action_connector = sandbox_action_connector
    handoff_provider = SQLiteHandoffQueueAdapter(settings.sandbox_sqlite_path)
    delivery_receipts = SQLiteDeliveryReceiptStore(settings.sandbox_sqlite_path)
    chat_provider = LocalChatAdapter(delivery_receipts)
    stt_provider = StubSpeechToTextAdapter()
    tts_provider = StubTextToSpeechAdapter()
    telephony_provider = LocalTelephonyAdapter()
    authoritative_resources = ChainedResourceProvider(
        sandbox_action_connector, ReferenceDataResourceProvider()
    )
else:
    default_action_connector = DisabledActionConnector()
    handoff_provider = SQLiteHandoffQueueAdapter(settings.sandbox_sqlite_path)
    delivery_receipts = SQLiteDeliveryReceiptStore(settings.sandbox_sqlite_path)
    chat_provider = LocalChatAdapter(delivery_receipts)
    stt_provider = StubSpeechToTextAdapter()
    tts_provider = StubTextToSpeechAdapter()
    telephony_provider = LocalTelephonyAdapter()
    authoritative_resources = ChainedResourceProvider(
        sandbox_action_connector, ReferenceDataResourceProvider()
    )
jurisdiction_profile = load_jurisdiction_profile(
    settings.jurisdiction_profile, settings.jurisdiction_config_path
)
jurisdiction_guard = JurisdictionGuard(
    jurisdiction_profile, enforce=settings.effective_jurisdiction_enforcement
)
consequential_connectors = {name: default_action_connector for name in ACTION_PERMISSIONS}
configured_action_registry = load_action_connector_registry(
    settings,
    sqlite_connectors={
        **{name: sandbox_action_connector for name in ACTION_SPECIFICATIONS},
        "issue_refund": DatabaseRefundConnector(),
    },
)
if configured_action_registry is not None:
    action_connectors = configured_action_registry
elif settings.effective_upstream_mode is UpstreamMode.SANDBOX:
    demo_bindings = [
        SQLiteActionBinding(
            action_name=name,
            binding_id=f"sqlite-demo:{name}",
            binding_version="1",
            contract_version="v1",
        )
        for name in ACTION_SPECIFICATIONS
    ]
    action_connectors = ActionConnectorRegistry(
        ActionRegistryConfig(bindings=demo_bindings),
        environment=settings.environment,
        sqlite_connectors={
            **{name: sandbox_action_connector for name in ACTION_SPECIFICATIONS},
            "issue_refund": DatabaseRefundConnector(),
        },
    )
else:
    action_connectors = {
        "issue_refund": default_action_connector,
        **consequential_connectors,
    }
core_gateway = ActionGateway(
    core_kernel,
    action_connectors,
    policy_registry=policy_registry,
    policy_resolver=policy_service,
)
core_engine = CoreEngine(core_kernel, core_gateway, RefundDecisionService())
consequential_action_service = ConsequentialActionService(
    core_kernel, core_gateway, authoritative_resources
)
action_bridge = ActionBridge(
    kernel=core_kernel,
    action_service=consequential_action_service,
    resources=authoritative_resources,
    connector_resolver=(
        action_connectors if callable(getattr(action_connectors, "resolve", None)) else None
    ),
)
action_worker = ActionDeliveryWorker(
    core_store,
    core_gateway,
    lease_seconds=settings.action_worker_lease_seconds,
)
reconciliation_worker = ReconciliationWorker(
    core_store,
    core_gateway,
    dispatch_stale_seconds=settings.action_reconciliation_delay_seconds,
)
conversation_runtime = ConversationRuntime(core_store)
ivr_adapter = IvrAdapter()


_POLICY_BY_PROCEDURE = {
    "cs_refund": active_refund_policy,
    "cs_eft_dispute": active_reg_e_policy,
    "fraud_alert_triage": active_fraud_policy,
}
_DEFAULT_PROCEDURE_BY_ACTION = {
    "issue_refund": "cs_refund",
    "issue_store_credit": "cs_refund",
    "update_case_status": "cs_refund",
    "file_eft_dispute": "cs_eft_dispute",
    "issue_provisional_credit": "cs_eft_dispute",
    "escalate_to_supervisor": "cs_refund",
    "add_case_note": "cs_refund",
    "flag_account": "fraud_alert_triage",
    "submit_sar": "fraud_alert_triage",
    "close_alert": "fraud_alert_triage",
}


def _require_action_access(actor: UserContext, action: str) -> None:
    if action not in ACTION_PERMISSIONS:
        raise ValidationError(f"Unknown consequential action: {action}")
    if actor.role is Role.CUSTOMER and action == "issue_refund":
        return
    _require_permission(actor, ACTION_PERMISSIONS[action])


def _action_policy(action: str, requested_procedure: str | None = None):
    procedure_id = (
        requested_procedure
        if requested_procedure in _POLICY_BY_PROCEDURE
        else _DEFAULT_PROCEDURE_BY_ACTION[action]
    )
    policy = _POLICY_BY_PROCEDURE[procedure_id]
    if action not in set(policy.rules.get("allowed_actions", [])):
        procedure_id = _DEFAULT_PROCEDURE_BY_ACTION[action]
        policy = _POLICY_BY_PROCEDURE[procedure_id]
    return procedure_id, policy


def _action_case_id(
    action: str,
    customer_id: str,
    conversation_id: str | None,
    arguments: dict[str, Any],
) -> str:
    if action == "issue_refund" and arguments.get("order_id"):
        material = f"{customer_id}:{arguments['order_id']}"
        prefix = "REFUND"
    else:
        material = repr((customer_id, conversation_id, action, arguments))
        prefix = action.replace("_", "-").upper()[:32]
    digest = hashlib.sha256(material.encode()).hexdigest()[:16].upper()
    return f"CASE-{prefix}-{digest}"


def _proposal_view(proposal) -> dict[str, Any]:
    value = proposal.model_dump(mode="json")
    value["safe_preview"] = value.pop("preview", proposal.preview)
    value["state"] = value["status"]
    return value


async def _create_action_proposal(
    *,
    actor: UserContext,
    customer_id: str,
    action: str,
    arguments: dict[str, Any],
    resource: AuthoritativeResourceRef | None,
    conversation_id: str | None,
    message_id: str | None,
    requested_procedure: str | None = None,
):
    _require_action_access(actor, action)
    procedure_id, policy = _action_policy(action, requested_procedure)
    return await action_bridge.propose(
        ActionIntent(
            action=action,
            arguments=arguments,
            resource_type=resource.resource_type if resource else None,
            resource_id=resource.resource_id if resource else None,
        ),
        context=TrustedActionContext(
            actor_id=actor.user_id,
            customer_id=customer_id,
            case_id=_action_case_id(action, customer_id, conversation_id, arguments),
            procedure_id=procedure_id,
            procedure_version=policy.version,
            policy_package_id=policy.package_id,
            conversation_id=conversation_id,
            message_id=message_id,
        ),
    )


async def _resolve_mcp_action_context(
    context,
    action: str | None = None,
    arguments: dict[str, Any] | None = None,
) -> TrustedActionContext:
    """Derive MCP identity from authenticated transport metadata, never tool args."""
    request = context.request_context.request
    if request is None:
        raise AuthorizationError("MCP request context is unavailable")
    actor = getattr(request.state, "user", None)
    if actor is None:
        raise AuthorizationError("MCP request is not authenticated")
    requested_customer = request.headers.get("X-Workflow-Customer-ID")
    if actor.role is Role.CUSTOMER:
        requested_customer = actor.user_id
    elif not requested_customer and settings.is_dev:
        requested_customer = "CUST-456"
    if not requested_customer:
        raise AuthorizationError("MCP host must bind X-Workflow-Customer-ID")
    customer = resolve_customer_context(actor, requested_customer)
    selected_action = action or "issue_refund"
    if action is not None:
        _require_action_access(actor, action)
    requested_procedure = request.headers.get("X-Workflow-Procedure-ID")
    procedure_id, policy = _action_policy(selected_action, requested_procedure)
    conversation_id = request.headers.get("X-Workflow-Conversation-ID") or str(
        context.request_id
    )
    message_id = request.headers.get("X-Workflow-Message-ID") or str(
        context.request_id
    )
    return TrustedActionContext(
        actor_id=actor.user_id,
        customer_id=customer.customer_id,
        case_id=_action_case_id(
            selected_action,
            customer.customer_id,
            conversation_id,
            arguments or {},
        ),
        procedure_id=procedure_id,
        procedure_version=policy.version,
        policy_package_id=policy.package_id,
        conversation_id=conversation_id,
        message_id=message_id,
    )


action_mcp_server = create_action_mcp_server(
    action_bridge,
    _resolve_mcp_action_context,
)
app.mount("/mcp", action_mcp_server.streamable_http_app(), name="action-mcp")


# --- Pydantic models ---


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10000, description="User message text")
    session_id: Optional[str] = Field(default=None, description="Existing session ID to continue")
    message_id: Optional[str] = Field(default=None, description="Stable provider message ID for dedupe")
    provider_id: str = Field(
        default="local-chat",
        min_length=1,
        max_length=100,
        description="Namespace assigned to the chat provider; dedupe is scoped to this value",
    )
    user_id: str = Field(
        min_length=1,
        max_length=100,
        description="Serviced customer identifier (kept as user_id for client compatibility)",
    )


class ChatResponse(BaseModel):
    response: str
    session_id: str
    action_proposals: list[dict[str, Any]] = Field(default_factory=list)


class ActionProposalRequest(BaseModel):
    """Host request for an untrusted intent; trusted context is server-derived."""

    customer_id: str = Field(min_length=1, max_length=100)
    action: str = Field(min_length=1, max_length=100)
    arguments: dict[str, Any] = Field(default_factory=dict)
    resource: AuthoritativeResourceRef | None = None
    conversation_id: str | None = Field(default=None, max_length=300)
    message_id: str | None = Field(default=None, max_length=300)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "customer_id": "CUST-456",
                    "action": "issue_refund",
                    "arguments": {
                        "order_id": "ORD-123",
                        "reason": "item not received",
                    },
                    "resource": {
                        "resource_type": "order",
                        "resource_id": "ORD-123",
                    },
                    "conversation_id": "demo-session-1",
                }
            ]
        }
    }


class RefundCommandRequest(BaseModel):
    customer_id: str = Field(min_length=1, max_length=100)
    order_id: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=3, max_length=1000)
    consent_evidence_ref: str = Field(min_length=3, max_length=500)


class RefundCommandResponse(BaseModel):
    action_id: str
    status: str
    outcome: dict | None


class IvrTurnRequest(BaseModel):
    provider_id: str = "local-ivr"
    message_id: str
    conversation_id: str
    customer_id: str
    transcript: str
    asr_confidence: float = Field(ge=0, le=1)
    interrupted: bool = False


class IvrTurnResponse(BaseModel):
    accepted: bool
    requires_readback: bool
    proposed_authority: str


class ConversationTurnRequest(BaseModel):
    provider_id: str = Field(default="local", min_length=1, max_length=100)
    message_id: str = Field(min_length=1, max_length=300)
    conversation_id: str = Field(min_length=1, max_length=300)
    customer_id: str = Field(min_length=1, max_length=100)
    channel: ChannelKind
    text: str = Field(min_length=1, max_length=10000)
    locale: str = "en-US"
    timezone: str = "America/Chicago"
    sequence: int | None = Field(default=None, ge=0)
    asr_confidence: float | None = Field(default=None, ge=0, le=1)
    interrupted: bool = False
    consent_snapshot: dict = Field(default_factory=dict)
    contains_dtmf_secret: bool = False
    secure_dtmf_capture: bool = False

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "provider_id": "sandbox-telephony",
                    "message_id": "CALL-1001:TURN-3",
                    "conversation_id": "CALL-1001",
                    "customer_id": "CUST-456",
                    "channel": "ivr",
                    "text": "The amount was seventy nine dollars and ninety nine cents",
                    "asr_confidence": 0.86,
                    "interrupted": False,
                    "consent_snapshot": {"recording": True, "transcription": True},
                }
            ]
        }
    }


class WebSocketTurnFrame(BaseModel):
    type: Literal["user_turn"] = "user_turn"
    provider_id: str = Field(default="local-websocket", min_length=1, max_length=100)
    message_id: str = Field(min_length=1, max_length=300)
    session_id: str | None = Field(default=None, max_length=300)
    user_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=10000)
    sequence: int | None = Field(default=None, ge=0)
    locale: str = "en-US"
    timezone: str = "America/Chicago"
    consent_snapshot: dict = Field(default_factory=dict)


class WebSocketResponseFrame(BaseModel):
    type: Literal["agent_response"] = "agent_response"
    session_id: str
    text: str
    risk: RiskLevel
    may_stream: bool
    action_proposals: list[dict[str, Any]] = Field(default_factory=list)


class CreateHandoffRequest(BaseModel):
    conversation_id: str
    case_id: str
    customer_id: str
    queue: str = "customer-service"
    priority: str = "normal"
    context: dict


class HandoffCallbackRequest(BaseModel):
    status: HandoffStatus
    assigned_agent_id: str | None = None


class PolicyDraftRequest(BaseModel):
    package_id: str
    procedure_id: str
    version: str
    jurisdiction: str = "NAM"
    rules: dict


class SandboxResourceRequest(BaseModel):
    resource_type: str
    resource_id: str
    payload: dict


class SandboxScenarioRequest(BaseModel):
    idempotency_key: str
    scenario: SandboxScenario


class ChatDeliveryRequest(BaseModel):
    message_id: str | None = None
    conversation_id: str
    customer_id: str
    text: str = Field(min_length=1, max_length=10000)
    metadata: dict = Field(default_factory=dict)


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
    upstream_mode: str
    jurisdiction_profile: str


class ActionBindingResponse(BaseModel):
    binding_id: str
    binding_version: str
    contract_version: str


class ActionCatalogItemResponse(BaseModel):
    name: str
    required_parameters: list[str]
    authoritative_parameters: list[str]
    requires_consent: bool
    requires_approval: bool
    permission: str
    available: bool
    binding: ActionBindingResponse | None = None


class ActionCatalogResponse(BaseModel):
    actions: list[ActionCatalogItemResponse]
    count: int


class ActionProposalResponse(BaseModel):
    proposal_id: str
    action: str
    payload: ActionPayload
    case_id: str
    customer_id: str
    actor_id: str
    procedure_id: str
    procedure_version: str
    policy_package_id: str
    idempotency_key: str
    resource_type: str | None = None
    resource_id: str | None = None
    resource_version: int | None = None
    conversation_id: str | None = None
    message_id: str | None = None
    connector_binding_id: str | None = None
    connector_binding_version: str | None = None
    contract_version: str | None = None
    safe_preview: dict[str, Any] = Field(default_factory=dict)
    status: ActionProposalStatus
    state: ActionProposalStatus
    confirmation_evidence_ref: str | None = None
    action_id: str | None = None
    created_at: str
    expires_at: str
    updated_at: str
    confirmed_at: str | None = None
    cancelled_at: str | None = None


class ActionProposalConfirmationResponse(ActionProposalResponse):
    action_record: ActionRecord | None = None


class ActionProposalListResponse(BaseModel):
    action_proposals: list[ActionProposalResponse]


class ActionStatusResponse(BaseModel):
    action: ActionRecord
    events: list[dict[str, Any]]


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


async def _generate_safe_turn(context: TurnContext, text: str) -> GeneratedTurn:
    """Run ADK proposal/response generation and the complete safety pipeline once."""
    with LogContext(session_id=context.conversation_id, user_id=context.actor_id):
        logger.info(
            "Conversation turn actor=%s customer=%s session=%s channel=%s",
            context.actor_id,
            context.customer_id,
            context.conversation_id,
            context.channel.value,
        )
        session = await session_service.get_session(
            app_name=settings.app_name,
            user_id=context.owner_id,
            session_id=context.conversation_id,
        )
        if session is None:
            session = await session_service.create_session(
                app_name=settings.app_name,
                user_id=context.owner_id,
                session_id=context.conversation_id,
                state={
                    "customer_id": context.customer_id,
                    "actor_id": context.actor_id,
                    "actor_role": context.actor_role,
                    "actor_permissions": context.actor_permissions,
                    "current_date": date.today().isoformat(),
                    "channel": context.channel.value,
                    "locale": context.locale,
                    "timezone": context.timezone,
                },
            )
        session.state["customer_id"] = context.customer_id
        session.state["current_date"] = date.today().isoformat()
        session.state["channel"] = context.channel.value

        response_parts: list[str] = []
        async for event in runner.run_async(
            user_id=context.owner_id,
            session_id=context.conversation_id,
            new_message=genai_types.Content(
                role="user", parts=[genai_types.Part(text=text)]
            ),
        ):
            if event.author == "router_agent" or not event.content or not event.content.parts:
                continue
            for part in event.content.parts:
                if part.text:
                    candidate = part.text.strip()
                    if candidate and (
                        not response_parts or candidate != response_parts[-1].strip()
                    ):
                        response_parts.append(part.text)

        response_text = "\n\n".join(response_parts) if response_parts else ""
        if not response_text.strip():
            response_text = (
                "I'm sorry, I wasn't able to process your request. "
                "Could you please rephrase or provide more details?"
            )

        active_procedure_id = session.state.get("current_procedure")
        active_step = session.state.get("current_step")
        procedure_def = registry.procedures.get(active_procedure_id)
        response_text, violations, verification = await steer_response(
            text=response_text,
            session_state=dict(session.state),
            procedure_id=active_procedure_id,
            current_step=active_step,
            procedure_def=procedure_def,
            generate_fn=None,
            max_iterations=2,
        )
        if violations:
            logger.warning(
                "Guardrail violations filtered from response (session=%s): %s",
                context.conversation_id,
                [violation.rule for violation in violations],
            )
        if verification and not verification.is_valid and verification.verdict != "NOT_APPLICABLE":
            logger.warning(
                "Reasoning verification result (session=%s): verdict=%s, findings=%d",
                context.conversation_id,
                verification.verdict,
                len(verification.findings),
            )
        risk = RiskLevel.INFORMATIONAL
        if active_procedure_id == "cs_eft_dispute":
            risk = RiskLevel.REGULATED
        elif active_procedure_id in {"cs_refund", "fraud_alert_triage"}:
            risk = RiskLevel.CONSEQUENTIAL
        proposal_views: list[dict[str, Any]] = []
        pending_intents = list(session.state.get("pending_action_intents", []))
        # Clear first so a failed proposal cannot be replayed silently on the next
        # turn. The model may propose it again after the customer corrects inputs.
        session.state["pending_action_intents"] = []
        trusted_actor = UserContext(
            user_id=context.actor_id,
            role=Role(context.actor_role),
            permissions=set(context.actor_permissions),
        )
        for raw_intent in pending_intents:
            try:
                resource_data = raw_intent.get("resource")
                resource = (
                    AuthoritativeResourceRef.model_validate(resource_data)
                    if resource_data
                    else None
                )
                proposal = await _create_action_proposal(
                    actor=trusted_actor,
                    customer_id=context.customer_id,
                    action=str(raw_intent["action"]),
                    arguments=dict(raw_intent.get("arguments", {})),
                    resource=resource,
                    conversation_id=context.conversation_id,
                    message_id=context.message_id,
                    requested_procedure=active_procedure_id,
                )
                proposal_views.append(_proposal_view(proposal))
            except Exception as exc:
                logger.warning(
                    "Action intent could not be prepared (conversation=%s action=%s type=%s)",
                    context.conversation_id,
                    raw_intent.get("action"),
                    type(exc).__name__,
                )
                response_text += (
                    "\n\nI could not prepare that action safely. No action was "
                    "executed; please verify the requested resource and details."
                )
        return GeneratedTurn(
            text=response_text,
            risk=risk,
            action_proposals=proposal_views,
        )


conversation_service = ConversationService(conversation_runtime, _generate_safe_turn)


# ===========================================================================
# Versioned API (v1)
# ===========================================================================


@app.post(f"{settings.api_prefix}/chat", response_model=ChatResponse, tags=["chat"])
async def chat_v1(
    request: ChatRequest,
    req: Request,
    actor: UserContext = Depends(get_current_user),
) -> ChatResponse:
    """Send a message to the workflow agent and get a response.

    If no session_id is provided, a new session is created.
    """
    # Normalize inbound message via channel abstraction
    inbound = await http_channel.receive({
        "message": request.message,
        "user_id": request.user_id,
        "session_id": request.session_id,
        "message_id": request.message_id,
    })
    customer = resolve_customer_context(actor, inbound.user_id)
    owner_id = session_owner_id(actor.user_id, customer.customer_id)

    session_id = inbound.session_id or str(uuid.uuid4())
    await core_store.initialize()
    result = await conversation_service.process_turn(
        MessageEnvelope(
            provider_id=(
                request.provider_id
                if actor.role in {Role.ADMIN, Role.INTEGRATION}
                else "direct-api"
            ),
            message_id=inbound.channel_message_id or f"local:{uuid.uuid4().hex}",
            conversation_id=session_id,
            customer_id=customer.customer_id,
            channel=ChannelKind.CHAT,
            text=inbound.text,
        ),
        actor_id=actor.user_id,
        actor_role=actor.role.value,
        actor_permissions=sorted(actor.permissions),
        owner_id=owner_id,
    )
    if result.duplicate:
        return ChatResponse(
            response="This message was already received.", session_id=session_id
        )
    return ChatResponse(
        response=result.response or "",
        session_id=session_id,
        action_proposals=result.action_proposals,
    )


@app.post(
    f"{settings.api_prefix}/core/refunds",
    response_model=RefundCommandResponse,
    tags=["core-actions"],
)
async def create_refund_command(
    request: RefundCommandRequest,
    actor: UserContext = Depends(get_current_user),
) -> RefundCommandResponse:
    """Execute a refund only through the deterministic action gateway."""
    customer = resolve_customer_context(actor, request.customer_id)
    _require_upstream_available()
    if actor.role is not Role.CUSTOMER and not actor.has_permission(Permission.REFUND_WRITE):
        from workflow_engine.errors import AuthorizationError

        raise AuthorizationError(
            "Refund command requires refund write permission",
            required_permission=Permission.REFUND_WRITE.value,
        )
    order = await OrderRepository.get_by_id(request.order_id)
    if order is None or order["customer_id"] != customer.customer_id:
        raise NotFoundError("Order", request.order_id)

    await core_store.initialize()
    case_digest = hashlib.sha256(
        f"{customer.customer_id}:{request.order_id}".encode()
    ).hexdigest()[:16].upper()
    result = await core_engine.process_refund(
        case_id=f"CASE-REFUND-{case_digest}",
        authenticated_customer_id=customer.customer_id,
        actor_id=actor.user_id,
        policy_package_id=active_refund_policy.package_id,
        procedure_version="1.0.0",
        order=OrderSnapshot(
            order_id=order["order_id"],
            customer_id=order["customer_id"],
            status=order["status"],
            days_since_delivery=order["days_since_delivery"] or 0,
            amount=order["total"],
            payment_method=order["payment_method"] or "original_payment_method",
            evidence_ref=f"orders-db:{order['order_id']}:{order['order_date']}",
        ),
        reason=request.reason,
        consent_evidence_ref=request.consent_evidence_ref,
    )
    return RefundCommandResponse(
        action_id=result.action_id,
        status=result.status.value,
        outcome=result.outcome,
    )


@app.post(
    f"{settings.api_prefix}/ivr/turns",
    response_model=IvrTurnResponse,
    tags=["ivr"],
)
async def accept_ivr_turn(
    request: IvrTurnRequest,
    actor: UserContext = Depends(get_current_user),
) -> IvrTurnResponse:
    customer = resolve_customer_context(actor, request.customer_id)
    turn = ivr_adapter.normalize(
        provider_message_id=request.message_id,
        conversation_id=request.conversation_id,
        customer_id=customer.customer_id,
        transcript=request.transcript,
        asr_confidence=request.asr_confidence,
        interrupted=request.interrupted,
    )
    await core_store.initialize()
    accepted = await conversation_runtime.accept(
        MessageEnvelope(
            provider_id=request.provider_id,
            message_id=turn.provider_message_id,
            conversation_id=turn.conversation_id,
            customer_id=turn.customer_id,
            channel=ChannelKind.IVR,
            text=turn.transcript,
            capabilities={
                "asr_confidence": turn.asr_confidence,
                "interrupted": turn.interrupted,
            },
        )
    )
    return IvrTurnResponse(
        accepted=accepted,
        requires_readback=turn.requires_readback,
        proposed_authority=turn.proposed_authority.value,
    )


def _require_permission(actor: UserContext, permission: Permission) -> None:
    if actor.role is not Role.ADMIN and not actor.has_permission(permission):
        raise AuthorizationError(
            f"Operation requires {permission.value}",
            required_permission=permission.value,
        )


def _require_upstream_available() -> None:
    if settings.effective_upstream_mode is UpstreamMode.DISABLED:
        raise HTTPException(
            status_code=503,
            detail=(
                "No upstream provider adapter is configured. The built-in sandbox "
                "is available only in development."
            ),
        )


@app.post(
    f"{settings.api_prefix}/conversations/turns",
    response_model=TurnResult,
    tags=["conversations"],
    summary="Process a chat or IVR turn through the shared safety pipeline",
)
async def process_conversation_turn(
    request: ConversationTurnRequest,
    actor: UserContext = Depends(get_current_user),
) -> TurnResult:
    customer = resolve_customer_context(actor, request.customer_id)
    if actor.role is Role.INTEGRATION:
        _require_permission(actor, Permission.CHANNEL_INGEST)
    owner_id = session_owner_id(actor.user_id, customer.customer_id)
    capabilities = {}
    jurisdiction_decision = jurisdiction_guard.evaluate_inbound(
        channel=request.channel,
        consent_snapshot=request.consent_snapshot,
        contains_dtmf_secret=request.contains_dtmf_secret,
        secure_dtmf_capture=request.secure_dtmf_capture,
    )
    if not jurisdiction_decision.allowed:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "JURISDICTION_CONTROL_BLOCKED",
                "blocks": jurisdiction_decision.blocks,
                "profile_id": jurisdiction_decision.profile_id,
            },
        )
    if request.channel is ChannelKind.IVR:
        if request.asr_confidence is None:
            raise ValidationError("IVR turns require asr_confidence")
        normalized = ivr_adapter.normalize(
            provider_message_id=request.message_id,
            conversation_id=request.conversation_id,
            customer_id=customer.customer_id,
            transcript=request.text,
            asr_confidence=request.asr_confidence,
            interrupted=request.interrupted,
        )
        capabilities = {
            "asr_confidence": normalized.asr_confidence,
            "interrupted": normalized.interrupted,
            "requires_readback": normalized.requires_readback,
        }
    await core_store.initialize()
    return await conversation_service.process_turn(
        MessageEnvelope(
            provider_id=(
                request.provider_id
                if actor.role in {Role.ADMIN, Role.INTEGRATION}
                else "direct-api"
            ),
            message_id=request.message_id,
            conversation_id=request.conversation_id,
            customer_id=customer.customer_id,
            channel=request.channel,
            text=request.text,
            locale=request.locale,
            timezone=request.timezone,
            sequence=request.sequence,
            capabilities=capabilities,
            consent_snapshot=request.consent_snapshot,
        ),
        actor_id=actor.user_id,
        actor_role=actor.role.value,
        actor_permissions=sorted(actor.permissions),
        owner_id=owner_id,
    )


@app.get(
    f"{settings.api_prefix}/actions/catalog",
    response_model=ActionCatalogResponse,
    tags=["action-bridge"],
    summary="List the closed action catalog and active provider bindings",
)
async def list_action_catalog(
    actor: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
    binding_capabilities = {
        item["action_name"]: item
        for item in (
            action_connectors.capabilities()
            if callable(getattr(action_connectors, "capabilities", None))
            else []
        )
    }
    actions = []
    for name, specification in ACTION_SPECIFICATIONS.items():
        permitted = actor.has_permission(ACTION_PERMISSIONS[name]) or (
            actor.role is Role.CUSTOMER and name == "issue_refund"
        )
        if actor.role is not Role.ADMIN and not permitted:
            continue
        actions.append(
            {
                "name": name,
                "required_parameters": sorted(specification.required_parameters),
                "authoritative_parameters": sorted(
                    specification.authoritative_parameters
                ),
                "requires_consent": specification.requires_consent,
                "requires_approval": specification.requires_approval,
                "permission": ACTION_PERMISSIONS[name].value,
                "available": (
                    name in binding_capabilities
                    if callable(getattr(action_connectors, "capabilities", None))
                    else True
                ),
                "binding": binding_capabilities.get(name),
            }
        )
    return {"actions": actions, "count": len(actions)}


@app.post(
    f"{settings.api_prefix}/action-proposals",
    response_model=ActionProposalResponse,
    tags=["action-bridge"],
    summary="Prepare a consequential action without executing it",
)
async def create_action_proposal(
    request: ActionProposalRequest,
    actor: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
    customer = resolve_customer_context(actor, request.customer_id)
    _require_upstream_available()
    await core_store.initialize()
    proposal = await _create_action_proposal(
        actor=actor,
        customer_id=customer.customer_id,
        action=request.action,
        arguments=request.arguments,
        resource=request.resource,
        conversation_id=request.conversation_id,
        message_id=request.message_id,
    )
    return _proposal_view(proposal)


@app.get(
    f"{settings.api_prefix}/action-proposals",
    response_model=ActionProposalListResponse,
    tags=["action-bridge"],
    summary="List action proposals created by the authenticated actor",
)
async def list_action_proposals(
    conversation_id: str | None = None,
    actor: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
    await core_store.initialize()
    proposals = await core_store.list_action_proposals(
        conversation_id=conversation_id,
        limit=100,
    )
    visible = [proposal for proposal in proposals if proposal.actor_id == actor.user_id]
    return {"action_proposals": [_proposal_view(item) for item in visible]}


async def _owned_proposal(proposal_id: str, actor: UserContext):
    proposal = await core_store.get_action_proposal(proposal_id)
    if proposal is None:
        raise NotFoundError("ActionProposal", proposal_id)
    resolve_customer_context(actor, proposal.customer_id)
    if proposal.actor_id != actor.user_id:
        raise AuthorizationError("Action proposal belongs to a different actor")
    return proposal


@app.get(
    f"{settings.api_prefix}/action-proposals/{{proposal_id}}",
    response_model=ActionProposalResponse,
    tags=["action-bridge"],
    summary="Get one actor- and customer-bound action proposal",
)
async def get_action_proposal(
    proposal_id: str,
    actor: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
    await core_store.initialize()
    proposal = await _owned_proposal(proposal_id, actor)
    proposal = await action_bridge.status(
        proposal.proposal_id,
        customer_id=proposal.customer_id,
        actor_id=actor.user_id,
    )
    return _proposal_view(proposal)


@app.post(
    f"{settings.api_prefix}/action-proposals/{{proposal_id}}/confirm",
    response_model=ActionProposalConfirmationResponse,
    tags=["action-bridge"],
    summary="Capture trusted host confirmation and submit through the typed gateway",
)
async def confirm_action_proposal(
    proposal_id: str,
    actor: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
    _require_upstream_available()
    await core_store.initialize()
    proposal = await _owned_proposal(proposal_id, actor)
    _require_action_access(actor, proposal.action)
    evidence = f"host-confirmation:{proposal_id}:{uuid.uuid4().hex}"
    confirmed = await action_bridge.confirm(
        proposal_id,
        context=ActionConfirmationContext(
            actor_id=actor.user_id,
            customer_id=proposal.customer_id,
            consent_evidence_ref=evidence,
            approval_evidence_ref=evidence,
        ),
    )
    response: dict[str, Any] = _proposal_view(confirmed)
    if confirmed.action_id:
        action = await core_store.get_action(confirmed.action_id)
        response["action_record"] = action.model_dump(mode="json") if action else None
    return response


@app.post(
    f"{settings.api_prefix}/action-proposals/{{proposal_id}}/cancel",
    response_model=ActionProposalResponse,
    tags=["action-bridge"],
    summary="Cancel a pending action proposal without executing it",
)
async def cancel_action_proposal(
    proposal_id: str,
    actor: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
    await core_store.initialize()
    proposal = await _owned_proposal(proposal_id, actor)
    cancelled = await action_bridge.cancel(
        proposal_id,
        context=ActionConfirmationContext(
            actor_id=actor.user_id,
            customer_id=proposal.customer_id,
        ),
    )
    return _proposal_view(cancelled)


@app.get(
    f"{settings.api_prefix}/actions/{{action_id}}",
    response_model=ActionStatusResponse,
    tags=["action-bridge"],
    summary="Get authoritative action status, outcome, and event history",
)
async def get_action_status(
    action_id: str,
    actor: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
    await core_store.initialize()
    action = await core_store.get_action(action_id)
    if action is None:
        raise NotFoundError("Action", action_id)
    case = await core_store.get_case(action.command.case_id)
    if case is None:
        raise NotFoundError("Case", action.command.case_id)
    resolve_customer_context(actor, case.customer_id)
    if action.command.actor_id != actor.user_id:
        raise AuthorizationError("Action belongs to a different actor")
    return {
        "action": action.model_dump(mode="json"),
        "events": await core_store.list_action_events(action_id),
    }


@app.post(
    f"{settings.api_prefix}/core/actions",
    tags=["core-actions"],
    summary="Submit a typed consequential action through the independent gateway",
)
async def submit_consequential_action(
    request: ConsequentialActionRequest,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    customer = resolve_customer_context(actor, request.customer_id)
    permission = ACTION_PERMISSIONS[request.payload.action]
    _require_permission(actor, permission)
    _require_upstream_available()
    if customer.customer_id != request.customer_id:
        raise AuthorizationError("Action customer binding mismatch")
    await core_store.initialize()
    result = await consequential_action_service.submit(request, actor_id=actor.user_id)
    return result.model_dump(mode="json")


@app.post(
    f"{settings.api_prefix}/integrations/ivr/stt:transcribe",
    response_model=SttResult,
    tags=["integration-development"],
    summary="Invoke the configured speech-to-text adapter",
)
async def transcribe_ivr(
    request: SttRequest,
    actor: UserContext = Depends(get_current_user),
) -> SttResult:
    _require_permission(actor, Permission.CHANNEL_INGEST)
    _require_upstream_available()
    return await stt_provider.transcribe(request)


@app.post(
    f"{settings.api_prefix}/integrations/ivr/tts:synthesize",
    response_model=TtsResult,
    tags=["integration-development"],
    summary="Invoke the configured text-to-speech adapter",
)
async def synthesize_ivr(
    request: TtsRequest,
    actor: UserContext = Depends(get_current_user),
) -> TtsResult:
    _require_permission(actor, Permission.CHANNEL_DELIVERY)
    _require_upstream_available()
    return await tts_provider.synthesize(request)


@app.post(
    f"{settings.api_prefix}/integrations/ivr/telephony/events",
    tags=["integration-development"],
    summary="Normalize a telephony-provider lifecycle event",
)
async def accept_telephony_event(
    event: TelephonyEvent,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    _require_permission(actor, Permission.CHANNEL_INGEST)
    _require_upstream_available()
    receipt = await telephony_provider.accept_event(event)
    return receipt.model_dump(mode="json")


@app.post(
    f"{settings.api_prefix}/integrations/chat/deliveries",
    response_model=ProviderReceipt,
    tags=["integration-development"],
    summary="Deliver a message through the configured chat-provider adapter",
)
async def deliver_chat_message(
    request: ChatDeliveryRequest,
    actor: UserContext = Depends(get_current_user),
) -> ProviderReceipt:
    customer = resolve_customer_context(actor, request.customer_id)
    _require_permission(actor, Permission.CHANNEL_DELIVERY)
    _require_upstream_available()
    return await chat_provider.send(
        {**request.model_dump(mode="json"), "customer_id": customer.customer_id}
    )


@app.post(
    f"{settings.api_prefix}/integrations/chat/receipts",
    response_model=ProviderReceipt,
    tags=["integration-development"],
    summary="Record an authenticated delivery receipt from a chat provider",
)
async def record_chat_receipt(
    receipt: ProviderReceipt,
    actor: UserContext = Depends(get_current_user),
) -> ProviderReceipt:
    _require_permission(actor, Permission.PROVIDER_CALLBACK)
    _require_upstream_available()
    return await delivery_receipts.record(receipt)


@app.get(
    f"{settings.api_prefix}/integrations/contracts",
    tags=["integration-development"],
    summary="Return machine-readable REST and WebSocket integration contracts",
)
async def integration_contracts() -> dict:
    return {
        "version": __version__,
        "upstream_mode": settings.effective_upstream_mode.value,
        "websocket_url": f"{settings.api_prefix}/ws/chat",
        "websocket_request_schema": WebSocketTurnFrame.model_json_schema(),
        "websocket_response_schema": WebSocketResponseFrame.model_json_schema(),
        "conversation_turn_schema": ConversationTurnRequest.model_json_schema(),
        "action_schema": ConsequentialActionRequest.model_json_schema(),
        "action_proposal_schema": ActionProposalRequest.model_json_schema(),
        "action_proposal_endpoints": {
            "catalog": f"{settings.api_prefix}/actions/catalog",
            "collection": f"{settings.api_prefix}/action-proposals",
            "confirm": f"{settings.api_prefix}/action-proposals/{{proposal_id}}/confirm",
            "cancel": f"{settings.api_prefix}/action-proposals/{{proposal_id}}/cancel",
            "status": f"{settings.api_prefix}/actions/{{action_id}}",
        },
        "mcp": {
            "url": "/mcp",
            "transport": "streamable-http",
            "model_tools": ["actions_prepare", "actions_get_status"],
            "host_confirmation_tool_exposed": False,
        },
        "stt_schema": SttRequest.model_json_schema(),
        "tts_schema": TtsRequest.model_json_schema(),
        "telephony_event_schema": TelephonyEvent.model_json_schema(),
        "chat_delivery_schema": ChatDeliveryRequest.model_json_schema(),
        "delivery_receipt_schema": ProviderReceipt.model_json_schema(),
        "jurisdiction_profile": jurisdiction_profile.model_dump(mode="json"),
    }


@app.get(
    f"{settings.api_prefix}/jurisdictions/current",
    tags=["governance"],
    summary="Return the active operational jurisdiction controls",
)
async def current_jurisdiction_profile() -> dict:
    return {
        **jurisdiction_profile.model_dump(mode="json"),
        "enforced": settings.effective_jurisdiction_enforcement,
    }


@app.post(
    f"{settings.api_prefix}/handoffs",
    tags=["human-handoff"],
    summary="Create and enqueue a human-agent handoff",
)
async def create_handoff(
    request: CreateHandoffRequest,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    customer = resolve_customer_context(actor, request.customer_id)
    _require_permission(actor, Permission.ESCALATION_CREATE)
    _require_upstream_available()
    case = await core_store.get_case(request.case_id)
    if case is None:
        raise NotFoundError("Core case", request.case_id)
    if case.customer_id != customer.customer_id:
        raise AuthorizationError("Handoff case does not belong to the serviced customer")
    record = await conversation_runtime.request_handoff(
        request.conversation_id,
        request.case_id,
        {**request.context, "customer_id": customer.customer_id},
    )
    receipt = await handoff_provider.enqueue(
        HandoffRequest(
            handoff_id=record.handoff_id,
            conversation_id=record.conversation_id,
            case_id=record.case_id,
            queue=request.queue,
            priority=request.priority,
            context=record.context,
        )
    )
    queued = await conversation_runtime.transition_handoff(
        record.handoff_id, HandoffStatus.QUEUED
    )
    return {
        "handoff": queued.model_dump(mode="json"),
        "provider_receipt": receipt.model_dump(mode="json"),
    }


@app.get(
    f"{settings.api_prefix}/handoffs/{{handoff_id}}",
    tags=["human-handoff"],
)
async def get_handoff(
    handoff_id: str,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    _require_permission(actor, Permission.CASE_READ)
    record = await core_store.get_handoff(handoff_id)
    if record is None:
        raise NotFoundError("Handoff", handoff_id)
    return record


@app.post(
    f"{settings.api_prefix}/handoffs/{{handoff_id}}/callbacks",
    tags=["human-handoff"],
    summary="Apply an authenticated human-agent platform status callback",
)
async def update_handoff_from_provider(
    handoff_id: str,
    request: HandoffCallbackRequest,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    _require_permission(actor, Permission.PROVIDER_CALLBACK)
    _require_upstream_available()
    record = await conversation_runtime.transition_handoff(
        handoff_id, request.status, request.assigned_agent_id
    )
    return record.model_dump(mode="json")


@app.get(f"{settings.api_prefix}/policies", tags=["policy-governance"])
async def list_policies(
    actor: UserContext = Depends(get_current_user),
) -> list[dict]:
    _require_permission(actor, Permission.ADMIN_READ)
    return [package.model_dump(mode="json") for package in await policy_repository.list()]


@app.post(f"{settings.api_prefix}/policies", tags=["policy-governance"])
async def create_policy_draft(
    request: PolicyDraftRequest,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    _require_permission(actor, Permission.ADMIN_WRITE)
    package = await policy_service.create_draft(
        PolicyPackage(
            package_id=request.package_id,
            procedure_id=request.procedure_id,
            version=request.version,
            jurisdiction=request.jurisdiction,
            author=actor.user_id,
            rules=request.rules,
        )
    )
    return package.model_dump(mode="json")


@app.post(
    f"{settings.api_prefix}/policies/{{package_id}}/approve",
    tags=["policy-governance"],
)
async def approve_policy(
    package_id: str,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    _require_permission(actor, Permission.ADMIN_WRITE)
    return (await policy_service.approve(package_id, actor.user_id)).model_dump(mode="json")


@app.post(
    f"{settings.api_prefix}/policies/{{package_id}}/activate",
    tags=["policy-governance"],
)
async def activate_policy(
    package_id: str,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    _require_permission(actor, Permission.ADMIN_WRITE)
    return (await policy_service.activate(package_id)).model_dump(mode="json")


@app.post(
    f"{settings.api_prefix}/policies/{{package_id}}/retire",
    tags=["policy-governance"],
)
async def retire_policy(
    package_id: str,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    _require_permission(actor, Permission.ADMIN_WRITE)
    return (await policy_service.retire(package_id)).model_dump(mode="json")


@app.get(f"{settings.api_prefix}/operations/actions", tags=["operations"])
async def list_core_actions(
    status: ActionStatus | None = None,
    limit: int = 100,
    actor: UserContext = Depends(get_current_user),
) -> list[dict]:
    _require_permission(actor, Permission.ADMIN_READ)
    return [
        action.model_dump(mode="json")
        for action in await core_store.list_actions(status=status, limit=min(limit, 1000))
    ]


@app.get(f"{settings.api_prefix}/operations/outbox", tags=["operations"])
async def list_core_outbox(
    status: OutboxStatus | None = None,
    limit: int = 100,
    actor: UserContext = Depends(get_current_user),
) -> list[dict]:
    _require_permission(actor, Permission.ADMIN_READ)
    return [
        record.model_dump(mode="json")
        for record in await core_store.list_outbox(status=status, limit=min(limit, 1000))
    ]


@app.get(
    f"{settings.api_prefix}/operations/actions/{{action_id}}/events",
    tags=["operations"],
)
async def list_core_action_events(
    action_id: str,
    actor: UserContext = Depends(get_current_user),
) -> list[dict]:
    _require_permission(actor, Permission.ADMIN_READ)
    action = await core_store.get_action(action_id)
    if action is None:
        raise NotFoundError("Action", action_id)
    return await core_store.list_action_events(action_id)


@app.get(
    f"{settings.api_prefix}/operations/conversation-quarantine",
    tags=["operations"],
)
async def list_conversation_quarantine(
    limit: int = 100,
    actor: UserContext = Depends(get_current_user),
) -> list[dict]:
    _require_permission(actor, Permission.ADMIN_READ)
    return await core_store.list_quarantined_messages(limit=min(limit, 1000))


@app.get(f"{settings.api_prefix}/operations/delivery-receipts", tags=["operations"])
async def list_delivery_receipts(
    limit: int = 100,
    actor: UserContext = Depends(get_current_user),
) -> list[dict]:
    _require_permission(actor, Permission.ADMIN_READ)
    return [
        receipt.model_dump(mode="json")
        for receipt in await delivery_receipts.list(limit=min(limit, 1000))
    ]


@app.get(f"{settings.api_prefix}/operations/audit-integrity", tags=["operations"])
async def verify_audit_integrity(
    actor: UserContext = Depends(get_current_user),
) -> dict:
    _require_permission(actor, Permission.ADMIN_READ)
    return await AuditRepository.verify_chain()


@app.post(f"{settings.api_prefix}/operations/workers/actions:run", tags=["operations"])
async def run_action_worker(
    actor: UserContext = Depends(get_current_user),
) -> dict:
    _require_permission(actor, Permission.ADMIN_WRITE)
    return (await action_worker.run_once()).__dict__


@app.post(
    f"{settings.api_prefix}/operations/workers/reconciliation:run",
    tags=["operations"],
)
async def run_reconciliation_worker(
    actor: UserContext = Depends(get_current_user),
) -> dict:
    _require_permission(actor, Permission.ADMIN_WRITE)
    return (await reconciliation_worker.run_once()).__dict__


if settings.is_dev:

    @app.put(
        f"{settings.api_prefix}/dev/sandbox/resources",
        tags=["sandbox-development"],
        summary="Seed an authoritative upstream resource for deterministic development",
    )
    async def put_sandbox_resource(
        request: SandboxResourceRequest,
        actor: UserContext = Depends(get_current_user),
    ) -> dict:
        _require_permission(actor, Permission.ADMIN_WRITE)
        return await sandbox_action_connector.put_resource(
            request.resource_type, request.resource_id, request.payload
        )


    @app.put(
        f"{settings.api_prefix}/dev/sandbox/action-scenarios",
        tags=["sandbox-development"],
        summary="Configure a deterministic action-provider failure scenario",
    )
    async def put_sandbox_scenario(
        request: SandboxScenarioRequest,
        actor: UserContext = Depends(get_current_user),
    ) -> dict:
        _require_permission(actor, Permission.ADMIN_WRITE)
        await sandbox_action_connector.set_scenario(
            request.idempotency_key, request.scenario
        )
        return request.model_dump(mode="json")


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
async def get_session_state_v1(
    session_id: str,
    user_id: str,
    actor: UserContext = Depends(get_current_user),
) -> SessionStateResponse:
    """Get the workflow state for a given session."""
    customer = resolve_customer_context(actor, user_id)
    session = await session_service.get_session(
        app_name=settings.app_name,
        user_id=session_owner_id(actor.user_id, customer.customer_id),
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
async def list_sessions_v1(
    user_id: str,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    """List all sessions for a user."""
    customer = resolve_customer_context(actor, user_id)
    resp = await session_service.list_sessions(
        app_name=settings.app_name,
        user_id=session_owner_id(actor.user_id, customer.customer_id),
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
    """WebSocket chat using the same complete response-safety path as REST."""
    if settings.auth_enabled:
        auth_header = websocket.headers.get("Authorization", "")
        token = auth_header[7:] if auth_header.startswith("Bearer ") else ""
        if not token:
            await websocket.close(code=4401, reason="Authentication required")
            return
        try:
            actor = decode_access_token(token)
        except WorkflowEngineError:
            await websocket.close(code=4401, reason="Invalid authentication")
            return
    else:
        actor = build_user_context("dev-user", Role.ADMIN)

    await websocket.accept()
    logger.info("WebSocket connection established actor=%s", actor.user_id)

    try:
        while True:
            data = await websocket.receive_json()
            try:
                frame = WebSocketTurnFrame.model_validate(data)
            except PydanticValidationError as exc:
                await websocket.send_json(
                    {
                        "type": "validation_error",
                        "errors": exc.errors(include_url=False, include_input=False),
                    }
                )
                continue
            inbound = await ws_channel.receive(frame.model_dump(mode="json"))
            customer = resolve_customer_context(actor, inbound.user_id)

            session_id = inbound.session_id or str(uuid.uuid4())
            customer_id = customer.customer_id
            owner_id = session_owner_id(actor.user_id, customer_id)
            await core_store.initialize()
            result = await conversation_service.process_turn(
                MessageEnvelope(
                    provider_id=(
                        frame.provider_id
                        if actor.role in {Role.ADMIN, Role.INTEGRATION}
                        else "direct-websocket"
                    ),
                    message_id=inbound.channel_message_id or f"ws:{uuid.uuid4().hex}",
                    conversation_id=session_id,
                    customer_id=customer_id,
                    channel=ChannelKind.CHAT,
                    text=inbound.text,
                    sequence=frame.sequence,
                    locale=frame.locale,
                    timezone=frame.timezone,
                    consent_snapshot=frame.consent_snapshot,
                ),
                actor_id=actor.user_id,
                actor_role=actor.role.value,
                actor_permissions=sorted(actor.permissions),
                owner_id=owner_id,
            )
            if result.duplicate:
                await websocket.send_json({
                    "type": "duplicate_suppressed",
                    "session_id": session_id,
                })
                continue
            if result.quarantined:
                await websocket.send_json(
                    {
                        "type": "message_quarantined",
                        "session_id": session_id,
                        "message_id": result.message_id,
                        "reason": "provider_sequence_gap",
                    }
                )
                continue
            await websocket.send_json(
                {
                    "type": "agent_response",
                    "session_id": session_id,
                    "text": result.response,
                    "risk": result.risk.value,
                    "may_stream": result.may_stream,
                    "action_proposals": result.action_proposals,
                }
            )
            await websocket.send_json({"type": "stream_end", "session_id": session_id})

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
async def metrics_v1(
    actor: UserContext = Depends(get_current_user),
) -> dict:
    """Basic operational metrics for monitoring dashboards."""
    _require_permission(actor, Permission.ADMIN_READ)
    active_procedures = executor_registry.list_active()
    await core_store.initialize()
    actions = await core_store.list_actions(limit=1000)
    outbox = await core_store.list_outbox(limit=1000)
    action_counts = {
        status.value: sum(action.status is status for action in actions)
        for status in ActionStatus
    }
    outbox_counts = {
        status.value: sum(record.status is status for record in outbox)
        for status in OutboxStatus
    }
    return {
        "procedures_loaded": len(registry.procedures),
        "active_procedures": len(active_procedures),
        "auth_enabled": settings.auth_enabled,
        "rate_limit_enabled": settings.rate_limit_enabled,
        "environment": settings.environment.value,
        "upstream_mode": settings.effective_upstream_mode.value,
        "jurisdiction_profile": jurisdiction_profile.profile_id,
        "actions": action_counts,
        "outbox": outbox_counts,
        "active_policy_packages": len(
            await policy_repository.list(PolicyLifecycle.ACTIVE)
        ),
    }


# ===========================================================================
# Legacy API routes (backward compatibility with v0.2.0 clients)
# ===========================================================================


@app.post("/api/chat", response_model=ChatResponse, tags=["legacy"], include_in_schema=False)
async def chat_legacy(
    request: ChatRequest,
    req: Request,
    actor: UserContext = Depends(get_current_user),
) -> ChatResponse:
    """Legacy chat endpoint — delegates to v1."""
    return await chat_v1(request, req, actor)


@app.get("/api/procedures", response_model=ProceduresResponse, tags=["legacy"], include_in_schema=False)
async def list_procedures_legacy() -> ProceduresResponse:
    return await list_procedures_v1()


@app.get("/api/session/{session_id}/state", response_model=SessionStateResponse, tags=["legacy"], include_in_schema=False)
async def get_session_state_legacy(
    session_id: str,
    user_id: str,
    actor: UserContext = Depends(get_current_user),
) -> SessionStateResponse:
    return await get_session_state_v1(session_id, user_id, actor)


@app.get("/api/customers", tags=["legacy"], include_in_schema=False)
async def list_customers_legacy() -> dict:
    return await list_customers_v1()


@app.get("/api/tables/{table_name}", tags=["legacy"], include_in_schema=False)
async def get_table_data_legacy(table_name: str) -> dict:
    return await get_table_data_v1(table_name)


@app.get("/api/sessions", tags=["legacy"], include_in_schema=False)
async def list_sessions_legacy(
    user_id: str,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    return await list_sessions_v1(user_id, actor)


# ===========================================================================
# Health check (unversioned)
# ===========================================================================


@app.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(
        status="ok",
        version=__version__,
        environment=settings.environment.value,
        procedures_loaded=len(registry.procedures),
        auth_enabled=settings.auth_enabled,
        upstream_mode=settings.effective_upstream_mode.value,
        jurisdiction_profile=jurisdiction_profile.profile_id,
    )


@app.get("/ready", tags=["system"])
async def readiness() -> dict:
    """Readiness check for stores, active policy, and configured upstream mode."""
    try:
        await core_store.initialize()
        await policy_repository.initialize()
        active = await policy_repository.list(PolicyLifecycle.ACTIVE)
    except Exception as exc:
        raise HTTPException(status_code=503, detail={"ready": False, "reason": type(exc).__name__}) from exc
    return {
        "ready": bool(active),
        "active_policy_packages": len(active),
        "upstream_mode": settings.effective_upstream_mode.value,
        "provider_bundle_loaded": provider_bundle is not None,
        "action_registry_loaded": callable(getattr(action_connectors, "resolve", None)),
        "action_registry_source": (
            "configured"
            if configured_action_registry is not None
            else "generated-demo"
            if settings.effective_upstream_mode is UpstreamMode.SANDBOX
            else "legacy-provider-bundle"
        ),
        "mcp_endpoint": "/mcp",
    }
    SQLiteDeliveryReceiptStore,
