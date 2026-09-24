"""Environment configuration.

The only place that reads environment variables. No model or deployment
names are hard-coded here; they come from .env.
"""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

from meeting_agent.errors import ConfigError

REQUIRED_AZURE_VARS = (
    "AZURE_OPENAI_ENDPOINT",
    "OPENAI_API_KEY",
    "OPENAI_API_VERSION",
    "CHAT_MODEL",
)


@dataclass(frozen=True)
class AzureOpenAISettings:
    endpoint: str
    api_key: str = field(repr=False)  # never shown in reprs, logs or tracebacks
    api_version: str
    chat_deployment: str
    embedding_deployment: str | None = None  # reserved for later Q&A work


def load_environment() -> None:
    """Load variables from a .env file, if present. Real env vars win."""
    load_dotenv(override=False)


def get_provider_name() -> str:
    """Return LLM_PROVIDER, lower-cased, or raise ConfigError if it is unset."""
    name = os.getenv("LLM_PROVIDER", "").strip().lower()
    if not name:
        raise ConfigError(
            "LLM_PROVIDER is not configured. Set it to 'mock' or 'azure' in your .env file."
        )
    return name


def get_azure_settings() -> AzureOpenAISettings:
    """Return validated Azure OpenAI settings, or raise ConfigError naming the gap."""
    values = {name: os.getenv(name, "").strip() for name in REQUIRED_AZURE_VARS}
    for name, value in values.items():
        if not value:
            raise ConfigError(
                f"{name} is not configured. Add it to your .env file (see .env.example)."
            )

    endpoint = values["AZURE_OPENAI_ENDPOINT"]
    if not endpoint.startswith("https://"):
        raise ConfigError(
            "AZURE_OPENAI_ENDPOINT must be an https:// URL, for example "
            "https://<resource>.cognitiveservices.azure.com/"
        )

    return AzureOpenAISettings(
        endpoint=endpoint,
        api_key=values["OPENAI_API_KEY"],
        api_version=values["OPENAI_API_VERSION"],
        chat_deployment=values["CHAT_MODEL"],
        embedding_deployment=os.getenv("EMBEDDING_MODEL", "").strip() or None,
    )
