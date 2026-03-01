"""Centralized application settings using Pydantic BaseSettings.

All configuration is loaded from environment variables or .env files,
with validation, type coercion, and environment profile support.
"""

from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Environment(str, Enum):
    DEV = "dev"
    STAGING = "staging"
    PRODUCTION = "production"


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
    def adk_session_db_url(self) -> str:
        """DB URL in the format ADK's DatabaseSessionService expects."""
        if "sqlite" in self.database_url:
            path = self.sqlite_path
            return f"sqlite:///{path}"
        # For PostgreSQL, ADK needs the sync driver URL
        return self.database_url.replace("+asyncpg", "")


@lru_cache()
def get_settings() -> Settings:
    """Get cached application settings singleton."""
    return Settings()
