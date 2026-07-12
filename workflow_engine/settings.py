"""Centralized application settings using Pydantic BaseSettings.

All configuration is loaded from environment variables or .env files,
with validation, type coercion, and environment profile support.
"""

from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings


class Environment(str, Enum):
    DEV = "dev"
    STAGING = "staging"
    PRODUCTION = "production"


class UpstreamMode(str, Enum):
    """How calls to systems outside the engine are handled."""

    DISABLED = "disabled"
    SANDBOX = "sandbox"
    PROVIDER = "provider"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # --- Environment ---
    environment: Environment = Field(default=Environment.DEV, description="Runtime environment")
    debug: bool = Field(default=False, description="Enable debug mode")

    # --- API ---
    api_host: str = Field(default="0.0.0.0", description="API bind host")
    api_port: int = Field(default=8000, description="API bind port")
    api_prefix: str = Field(default="/api/v1", description="API route prefix")
    cors_origins: list[str] = Field(
        default=["http://localhost:8001", "http://localhost:3000"],
        description="Allowed CORS origins",
    )

    # --- Database ---
    database_url: str = Field(
        default="sqlite+aiosqlite:///data/workflow.db",
        description="Database connection URL (SQLite for dev, PostgreSQL for production)",
    )
    reference_data_database_url: str = Field(
        default="sqlite+aiosqlite:///data/workflow.db",
        description="SQLite reference/demo business repository and local audit URL",
    )
    seed_reference_data: Optional[bool] = Field(
        default=None,
        description="Defaults true in development and false elsewhere",
    )
    adk_session_database_url: str = Field(
        default="sqlite+aiosqlite:///data/adk_sessions_v2.db",
        description="ADK 2.x session/event database URL (kept separate from domain data)",
    )
    policy_database_url: Optional[str] = Field(
        default=None,
        description="Policy repository URL; defaults to DATABASE_URL",
    )
    core_store_adapter_factory: Optional[str] = Field(
        default=None,
        description="Trusted package.module:callable factory for a non-SQLite CoreStore",
    )
    policy_repository_adapter_factory: Optional[str] = Field(
        default=None,
        description="Trusted package.module:callable factory for a non-SQLite PolicyRepository",
    )
    db_pool_size: int = Field(default=5, description="Database connection pool size")
    db_max_overflow: int = Field(default=10, description="Max overflow connections")
    db_pool_timeout: int = Field(default=30, description="Pool checkout timeout in seconds")
    db_echo: bool = Field(default=False, description="Echo SQL queries (debug)")

    # --- LLM ---
    google_api_key: Optional[str] = Field(default=None, description="Google AI API key")
    google_genai_use_vertexai: bool = Field(default=False, description="Use Vertex AI backend")
    llm_model: str = Field(default="gemini-2.5-flash", description="LLM model name")
    llm_temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    llm_top_p: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    llm_top_k: Optional[int] = Field(default=None, ge=1)
    llm_max_output_tokens: Optional[int] = Field(default=None, ge=1)

    # --- Auth ---
    auth_enabled: bool = Field(default=False, description="Enable JWT authentication")
    auth_secret_key: str = Field(
        default="dev-secret-key-change-in-production",
        description="JWT signing secret",
    )
    auth_algorithm: str = Field(default="HS256", description="JWT algorithm")
    auth_token_expire_minutes: int = Field(default=480, description="Token expiry in minutes")
    auth_issuer: str = Field(default="workflow-engine", description="JWT issuer")

    # --- Policy governance ---
    jurisdiction_profile: str = Field(default="NAM", description="Active jurisdiction profile")
    jurisdiction_config_path: Optional[Path] = Field(
        default=None,
        description="Optional YAML/JSON file overriding operational jurisdiction controls",
    )
    jurisdiction_enforce: Optional[bool] = Field(
        default=None,
        description="Defaults to observe-only in development and enforced elsewhere",
    )
    policy_signing_key: str = Field(
        default="dev-policy-signing-key",
        description="HMAC policy signing key; load from a secret manager in production",
    )
    policy_signing_key_id: str = Field(default="primary")
    policy_verification_keys: dict[str, str] = Field(
        default_factory=dict,
        description="Old key-id to secret mapping retained only for signature verification",
    )
    policy_author: str = Field(default="operations-author")
    policy_approver: str = Field(default="risk-approver")

    # --- Upstream adapters ---
    upstream_mode: Optional[UpstreamMode] = Field(
        default=None,
        description=(
            "Upstream adapter mode. Defaults to sandbox in development and disabled "
            "elsewhere; production never permits sandbox mode."
        ),
    )
    sandbox_database_url: str = Field(
        default="sqlite+aiosqlite:///data/upstream_sandbox.db",
        description="SQLite-backed deterministic upstream emulator used only outside production",
    )
    action_worker_lease_seconds: int = Field(default=30, ge=5, le=3600)
    action_reconciliation_delay_seconds: int = Field(default=30, ge=0, le=86400)

    # --- Rate Limiting ---
    rate_limit_enabled: bool = Field(default=False, description="Enable rate limiting")
    rate_limit_requests: int = Field(default=100, description="Max requests per window")
    rate_limit_window_seconds: int = Field(default=60, description="Rate limit window")

    # --- Logging ---
    log_level: str = Field(default="INFO", description="Log level")
    log_format: str = Field(default="json", description="Log format: json or text")
    log_file: Optional[str] = Field(default=None, description="Log file path (None for stdout)")

    # --- Observability ---
    metrics_enabled: bool = Field(default=False, description="Enable Prometheus metrics")
    tracing_enabled: bool = Field(default=False, description="Enable OpenTelemetry tracing")
    tracing_endpoint: Optional[str] = Field(default=None, description="OTLP endpoint")

    # --- Automated Reasoning ---
    reasoning_enabled: bool = Field(default=True, description="Enable Z3/SymPy reasoning verification")
    reasoning_max_iterations: int = Field(default=2, ge=0, le=5, description="Max rewrite iterations for behavior steering")
    compliance_enabled: bool = Field(default=True, description="Enable domain-specific compliance checks")

    # --- Session ---
    session_ttl_hours: int = Field(default=24, description="Session TTL in hours")
    app_name: str = Field(default="workflow_engine", description="Application name for ADK")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid:
            raise ValueError(f"log_level must be one of {valid}")
        return upper

    @model_validator(mode="after")
    def validate_production_secrets(self):
        if self.is_production and self.policy_signing_key == "dev-policy-signing-key":
            raise ValueError("POLICY_SIGNING_KEY must be changed in production")
        if (
            self.is_production
            and self.auth_enabled
            and self.auth_secret_key == "dev-secret-key-change-in-production"
        ):
            raise ValueError("AUTH_SECRET_KEY must be changed when production auth is enabled")
        if self.policy_author == self.policy_approver:
            raise ValueError("Policy author and approver must be different")
        if self.is_production and self.upstream_mode is UpstreamMode.SANDBOX:
            raise ValueError("UPSTREAM_MODE=sandbox is forbidden in production")
        if self.is_production and "*" in self.cors_origins:
            raise ValueError("Wildcard CORS origins are forbidden in production")
        if self.auth_algorithm not in {"HS256", "HS384", "HS512"}:
            raise ValueError("AUTH_ALGORITHM must be an approved HMAC JWT algorithm")
        if self.is_production and not self.auth_enabled:
            raise ValueError("AUTH_ENABLED must be true in production")
        if self.is_production and self.effective_seed_reference_data:
            raise ValueError("SEED_REFERENCE_DATA must be false in production")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION

    @property
    def is_dev(self) -> bool:
        return self.environment == Environment.DEV

    @property
    def sqlite_path(self) -> Optional[Path]:
        """Extract SQLite file path from database URL, or None for non-SQLite."""
        if "sqlite" in self.database_url:
            path_part = self.database_url.split("///")[-1]
            return Path(path_part)
        return None

    @property
    def reference_data_sqlite_path(self) -> Path:
        if not self.reference_data_database_url.startswith("sqlite"):
            raise ValueError("The built-in reference-data repository requires SQLite")
        return Path(self.reference_data_database_url.split("///", 1)[-1])

    @property
    def effective_seed_reference_data(self) -> bool:
        if self.seed_reference_data is not None:
            return self.seed_reference_data
        return self.is_dev

    @property
    def adk_session_db_url(self) -> str:
        """Async SQLAlchemy URL required by ADK 2.x DatabaseSessionService."""
        return self.adk_session_database_url

    @property
    def effective_policy_database_url(self) -> str:
        return self.policy_database_url or self.database_url

    @property
    def effective_upstream_mode(self) -> UpstreamMode:
        if self.upstream_mode is not None:
            return self.upstream_mode
        return UpstreamMode.SANDBOX if self.is_dev else UpstreamMode.DISABLED

    @property
    def sandbox_sqlite_path(self) -> Path:
        if not self.sandbox_database_url.startswith("sqlite"):
            raise ValueError("The built-in sandbox adapter requires a SQLite database URL")
        return Path(self.sandbox_database_url.split("///", 1)[-1])

    @property
    def effective_jurisdiction_enforcement(self) -> bool:
        if self.jurisdiction_enforce is not None:
            return self.jurisdiction_enforce
        return not self.is_dev


@lru_cache()
def get_settings() -> Settings:
    """Get cached application settings singleton."""
    return Settings()
