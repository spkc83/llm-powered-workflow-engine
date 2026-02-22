"""LLM model configuration loaded from environment variables.

Creates a google.genai Client and Gemini model instances that are passed
to ADK agents. Users can configure the model name and generation parameters
via .env or environment variables.

Environment variables:
    GOOGLE_API_KEY          — Google AI API key (required)
    GOOGLE_GENAI_USE_VERTEXAI — Set to "TRUE" to use Vertex AI backend
    LLM_MODEL               — Model name (default: "gemini-2.5-flash")
    LLM_TEMPERATURE         — Sampling temperature, 0.0-2.0 (default: model default)
    LLM_TOP_P               — Top-p nucleus sampling (default: model default)
    LLM_TOP_K               — Top-k sampling (default: model default)
    LLM_MAX_OUTPUT_TOKENS   — Maximum output tokens (default: model default)
"""

import os

from google.genai import Client
from google.genai.types import GenerateContentConfig
from google.adk.models.google_llm import Gemini


def _float_or_none(key: str) -> float | None:
    val = os.getenv(key)
    if val is None or val.strip() == "":
        return None
    return float(val)


def _int_or_none(key: str) -> int | None:
    val = os.getenv(key)
    if val is None or val.strip() == "":
        return None
    return int(val)


def get_model_name() -> str:
    """Return the configured LLM model name."""
    return os.getenv("LLM_MODEL", "gemini-2.5-flash")


def get_genai_client() -> Client:
    """Create and return a google.genai Client instance.

    The Client picks up GOOGLE_API_KEY and GOOGLE_GENAI_USE_VERTEXAI
    from environment variables automatically. You can also pass an
    explicit api_key if GOOGLE_API_KEY is not set in the environment.
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    use_vertexai = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "FALSE").upper() == "TRUE"

    return Client(
        api_key=api_key if not use_vertexai else None,
        vertexai=use_vertexai,
    )


def get_generate_content_config() -> GenerateContentConfig | None:
    """Build a GenerateContentConfig from environment variables.

    Returns None if no generation parameters are configured, letting the
    model use its own defaults.
    """
    temperature = _float_or_none("LLM_TEMPERATURE")
    top_p = _float_or_none("LLM_TOP_P")
    top_k = _float_or_none("LLM_TOP_K")
    max_output_tokens = _int_or_none("LLM_MAX_OUTPUT_TOKENS")

    # Only create config if at least one parameter is set
    if all(v is None for v in [temperature, top_p, top_k, max_output_tokens]):
        return None

    return GenerateContentConfig(
        temperature=temperature,
        top_p=top_p,
        top_k=top_k,
        max_output_tokens=max_output_tokens,
    )


def create_model() -> Gemini:
    """Create a Gemini model instance configured with the genai Client.

    Returns a Gemini BaseLlm instance that can be passed directly to
    ADK Agent's ``model`` parameter.  When a ``GOOGLE_API_KEY`` (or Vertex AI
    credentials) is available the model is wired to an explicit
    ``google.genai.Client``, giving centralised control over authentication
    and connection settings.  When no credentials are present (e.g. in a test
    environment) the ``Gemini`` instance is returned without an injected
    client — ADK will create one lazily when the agent actually runs.
    """
    model_name = get_model_name()
    gemini = Gemini(model=model_name)

    try:
        client = get_genai_client()
        # Inject our configured Client before the cached_property is accessed,
        # overriding the default Client that Gemini would create internally.
        gemini.__dict__["api_client"] = client
    except ValueError:
        # No API key / credentials available (e.g. test environment).
        # Leave gemini.api_client to be created lazily by ADK at runtime.
        pass

    return gemini
