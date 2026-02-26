"""LLM model configuration using centralized settings.

Creates a google.genai Client and Gemini model instances that are passed
to ADK agents. All configuration is loaded from the Settings singleton.
"""

from google.genai import Client
from google.genai.types import GenerateContentConfig
from google.adk.models.google_llm import Gemini

from .settings import get_settings


def get_model_name() -> str:
    """Return the configured LLM model name."""
    return get_settings().llm_model


def get_genai_client() -> Client:
    """Create and return a google.genai Client instance."""
    settings = get_settings()
    return Client(
        api_key=settings.google_api_key if not settings.google_genai_use_vertexai else None,
        vertexai=settings.google_genai_use_vertexai,
    )


def get_generate_content_config() -> GenerateContentConfig | None:
    """Build a GenerateContentConfig from settings.

    Returns None if no generation parameters are configured, letting the
    model use its own defaults.
    """
    settings = get_settings()
    temperature = settings.llm_temperature
    top_p = settings.llm_top_p
    top_k = settings.llm_top_k
    max_output_tokens = settings.llm_max_output_tokens

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
    ADK Agent's ``model`` parameter.
    """
    model_name = get_model_name()
    gemini = Gemini(model=model_name)

    try:
        client = get_genai_client()
        gemini.__dict__["api_client"] = client
    except ValueError:
        # No API key / credentials available (e.g. test environment).
        pass

    return gemini
