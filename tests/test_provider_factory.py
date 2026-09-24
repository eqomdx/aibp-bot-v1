from unittest.mock import MagicMock

import pytest

from conftest import chat_response
from meeting_agent.config import get_provider_name
from meeting_agent.errors import ConfigError
from meeting_agent.meeting_service import MeetingService
from meeting_agent.providers import azure_openai, factory
from meeting_agent.providers.azure_openai import AzureOpenAIProvider
from meeting_agent.providers.mock import MockLLMProvider


@pytest.fixture
def azure_sdk(monkeypatch):
    """Replace the AzureOpenAI SDK class so nothing real is built or called."""
    sdk_class = MagicMock(name="AzureOpenAI")
    sdk_class.return_value.chat.completions.create.return_value = chat_response(
        "# Meeting Summary\n\n## Overview\nFrom Azure."
    )
    monkeypatch.setattr(azure_openai, "AzureOpenAI", sdk_class)
    return sdk_class


def test_mock_is_selected_without_touching_azure(azure_sdk):
    provider = factory.create_provider("mock")

    assert isinstance(provider, MockLLMProvider)
    azure_sdk.assert_not_called()  # no Azure client, and no Azure settings needed


def test_azure_is_selected_with_azure_config(azure_env, azure_sdk):
    provider = factory.create_provider("azure")

    assert isinstance(provider, AzureOpenAIProvider)
    azure_sdk.assert_called_once()


def test_azure_without_config_fails_cleanly():
    with pytest.raises(ConfigError, match="AZURE_OPENAI_ENDPOINT is not configured"):
        factory.create_provider("azure")


def test_unknown_provider_is_rejected():
    with pytest.raises(ConfigError, match="'openai' is not supported. Use one of: mock, azure."):
        factory.create_provider("openai")


def test_provider_name_is_required():
    with pytest.raises(ConfigError, match="LLM_PROVIDER is not configured"):
        get_provider_name()


def test_provider_name_is_case_and_space_insensitive(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "  Azure ")

    assert get_provider_name() == "azure"


@pytest.mark.parametrize("name", ["mock", "azure"])
def test_same_meeting_service_works_with_either_provider(azure_env, azure_sdk, name):
    """Switching providers changes only the object passed in, never MeetingService."""
    service = MeetingService(factory.create_provider(name))

    summary = service.summarise("Kat: We need the demo ready for Friday.")

    assert summary.startswith("# Meeting Summary")
