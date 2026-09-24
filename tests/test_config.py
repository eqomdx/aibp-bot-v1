import pytest

from conftest import FAKE_API_KEY
from meeting_agent.config import REQUIRED_AZURE_VARS, get_azure_settings
from meeting_agent.errors import ConfigError


def test_complete_configuration_loads(azure_env):
    settings = get_azure_settings()

    assert settings.endpoint == azure_env["AZURE_OPENAI_ENDPOINT"]
    assert settings.api_key == FAKE_API_KEY
    assert settings.api_version == "2024-12-01-preview"
    assert settings.chat_deployment == "test-deployment"
    assert settings.embedding_deployment == "test-embeddings"


@pytest.mark.parametrize("missing", REQUIRED_AZURE_VARS)
def test_missing_required_value_is_named(azure_env, monkeypatch, missing):
    monkeypatch.delenv(missing)

    with pytest.raises(ConfigError) as excinfo:
        get_azure_settings()

    assert str(excinfo.value).startswith(f"{missing} is not configured.")
    assert FAKE_API_KEY not in str(excinfo.value)


def test_blank_value_counts_as_missing(azure_env, monkeypatch):
    monkeypatch.setenv("CHAT_MODEL", "   ")

    with pytest.raises(ConfigError, match="CHAT_MODEL is not configured"):
        get_azure_settings()


def test_embedding_model_is_optional(azure_env, monkeypatch):
    monkeypatch.delenv("EMBEDDING_MODEL")

    assert get_azure_settings().embedding_deployment is None


def test_non_https_endpoint_is_rejected(azure_env, monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "test-resource.cognitiveservices.azure.com")

    with pytest.raises(ConfigError, match="https://"):
        get_azure_settings()
