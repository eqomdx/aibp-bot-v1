from unittest.mock import MagicMock

import openai
import pytest

from conftest import FAKE_API_KEY, chat_response
from meeting_agent.errors import LLMProviderError
from meeting_agent.providers import azure_openai
from meeting_agent.providers.azure_openai import AzureOpenAIProvider


@pytest.fixture
def sdk(monkeypatch):
    """Replace the AzureOpenAI class so no real client or request is made."""
    sdk_class = MagicMock(name="AzureOpenAI")
    client = sdk_class.return_value
    client.chat.completions.create.return_value = chat_response("# Meeting Summary")
    monkeypatch.setattr(azure_openai, "AzureOpenAI", sdk_class)
    return sdk_class


def test_client_uses_azure_endpoint_key_and_api_version(sdk, settings):
    AzureOpenAIProvider(settings)

    sdk.assert_called_once_with(
        api_key=FAKE_API_KEY,
        azure_endpoint="https://test-resource.cognitiveservices.azure.com/",
        api_version="2024-12-01-preview",
    )


def test_real_client_targets_azure_not_openai(settings):
    """Builds a real (offline) SDK client to confirm where requests would go."""
    provider = AzureOpenAIProvider(settings)

    base_url = str(provider.client.base_url)
    assert base_url.startswith("https://test-resource.cognitiveservices.azure.com/")
    assert "api.openai.com" not in base_url


def test_chat_model_is_sent_as_deployment(sdk, settings):
    AzureOpenAIProvider(settings).generate("system text", "user text")

    kwargs = sdk.return_value.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "test-deployment"
    assert kwargs["messages"] == [
        {"role": "system", "content": "system text"},
        {"role": "user", "content": "user text"},
    ]


def test_response_text_is_extracted(sdk, settings):
    sdk.return_value.chat.completions.create.return_value = chat_response("  # Meeting Summary\n\n")

    assert AzureOpenAIProvider(settings).generate("s", "u") == "# Meeting Summary"


@pytest.mark.parametrize("content", ["", "   ", None], ids=["empty", "whitespace", "none"])
def test_empty_response_fails(sdk, settings, content):
    sdk.return_value.chat.completions.create.return_value = chat_response(content)

    with pytest.raises(LLMProviderError, match="empty response"):
        AzureOpenAIProvider(settings).generate("s", "u")


def test_no_choices_fails(sdk, settings):
    sdk.return_value.chat.completions.create.return_value = MagicMock(choices=[])

    with pytest.raises(LLMProviderError, match="no response choices"):
        AzureOpenAIProvider(settings).generate("s", "u")


def test_content_filtered_response_fails(sdk, settings):
    sdk.return_value.chat.completions.create.return_value = chat_response(
        None, finish_reason="content_filter"
    )

    with pytest.raises(LLMProviderError, match="content filter"):
        AzureOpenAIProvider(settings).generate("s", "u")


@pytest.mark.parametrize(
    ("make_error", "expected"),
    [
        (lambda req, se: se(openai.AuthenticationError, 401), "rejected the API key"),
        (lambda req, se: se(openai.PermissionDeniedError, 403), "not allowed to use deployment"),
        (
            lambda req, se: se(openai.NotFoundError, 404, code="DeploymentNotFound"),
            "deployment 'test-deployment' was not found.*CHAT_MODEL must match",
        ),
        (lambda req, se: se(openai.NotFoundError, 404), "CHAT_MODEL matches the Azure deployment"),
        (lambda req, se: se(openai.RateLimitError, 429), "rate limit"),
        (lambda req, se: openai.APIConnectionError(request=req), "Could not reach Azure OpenAI"),
        (lambda req, se: openai.APITimeoutError(request=req), "Could not reach Azure OpenAI"),
        (
            lambda req, se: se(openai.BadRequestError, 400, code="content_filter"),
            "content filter blocked the request",
        ),
        (
            lambda req, se: se(openai.InternalServerError, 500, "server melted"),
            "HTTP 500.*server melted",
        ),
    ],
    ids=[
        "auth", "no-access", "deployment-not-found", "other-404", "rate-limit",
        "connection", "timeout", "content-filter", "server-error",
    ],
)
def test_api_errors_become_useful_app_errors(
    sdk, settings, api_request, status_error, make_error, expected
):
    sdk.return_value.chat.completions.create.side_effect = make_error(api_request, status_error)

    with pytest.raises(LLMProviderError, match=expected) as excinfo:
        AzureOpenAIProvider(settings).generate("s", "u")

    assert FAKE_API_KEY not in str(excinfo.value)
    # The raw SDK exception is not chained, so users see one clean message.
    assert excinfo.value.__cause__ is None


def test_settings_repr_hides_api_key(settings):
    assert FAKE_API_KEY not in repr(settings)
