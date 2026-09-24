"""Choose and build the LLM provider named by LLM_PROVIDER.

The only place that knows which providers exist. Each builder runs only
when its provider is selected, so Azure settings are read (and the Azure
client created) only for LLM_PROVIDER=azure.
"""

from collections.abc import Callable

from meeting_agent.config import get_azure_settings
from meeting_agent.errors import ConfigError
from meeting_agent.providers.azure_openai import AzureOpenAIProvider
from meeting_agent.providers.base import LLMProvider
from meeting_agent.providers.mock import MockLLMProvider

PROVIDER_BUILDERS: dict[str, Callable[[], LLMProvider]] = {
    "mock": MockLLMProvider,
    "azure": lambda: AzureOpenAIProvider(get_azure_settings()),
}


def create_provider(name: str) -> LLMProvider:
    """Return a ready provider for `name`, or raise ConfigError if it is unknown."""
    builder = PROVIDER_BUILDERS.get(name)
    if builder is None:
        supported = ", ".join(PROVIDER_BUILDERS)
        raise ConfigError(f"LLM_PROVIDER '{name}' is not supported. Use one of: {supported}.")
    return builder()
