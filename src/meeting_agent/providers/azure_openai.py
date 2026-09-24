"""Azure OpenAI provider.

Only talks to Azure OpenAI: builds the client, sends one chat request,
returns plain text, and turns SDK errors into readable LLMProviderErrors.
No meeting-specific logic lives here.
"""

import openai
from openai import AzureOpenAI

from meeting_agent.config import AzureOpenAISettings
from meeting_agent.errors import LLMProviderError


class AzureOpenAIProvider:
    def __init__(self, settings: AzureOpenAISettings, client: AzureOpenAI | None = None):
        self.settings = settings
        self.client = client or AzureOpenAI(
            api_key=settings.api_key,
            azure_endpoint=settings.endpoint,
            api_version=settings.api_version,
        )

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        deployment = self.settings.chat_deployment
        try:
            response = self.client.chat.completions.create(
                model=deployment,  # on Azure, "model" is the deployment name
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except openai.OpenAIError as exc:
            raise self._to_provider_error(exc) from None

        return self._extract_text(response)

    def _extract_text(self, response) -> str:
        choices = getattr(response, "choices", None) or []
        if not choices:
            raise LLMProviderError("Azure OpenAI returned no response choices.")

        choice = choices[0]
        if getattr(choice, "finish_reason", None) == "content_filter":
            raise LLMProviderError(
                "Azure OpenAI's content filter blocked the response. "
                "Review the transcript for content that may trigger the filter."
            )

        text = (getattr(choice.message, "content", None) or "").strip()
        if not text:
            raise LLMProviderError("Azure OpenAI returned an empty response. Try running again.")
        return text

    def _to_provider_error(self, exc: openai.OpenAIError) -> LLMProviderError:
        endpoint = self.settings.endpoint
        deployment = self.settings.chat_deployment

        if isinstance(exc, openai.AuthenticationError):
            return LLMProviderError(
                f"Azure OpenAI rejected the API key for {endpoint}. Check that "
                "OPENAI_API_KEY in .env is a key for this Azure resource."
            )
        if isinstance(exc, openai.PermissionDeniedError):
            return LLMProviderError(
                f"The API key is not allowed to use deployment '{deployment}' at {endpoint}."
            )
        if isinstance(exc, openai.NotFoundError):
            if _error_field(exc, "code") == "DeploymentNotFound":
                return LLMProviderError(
                    f"Azure deployment '{deployment}' was not found at {endpoint}. "
                    "CHAT_MODEL must match the Azure deployment name exactly."
                )
            return LLMProviderError(
                f"Azure OpenAI returned 'not found' for deployment '{deployment}'. Check that "
                "CHAT_MODEL matches the Azure deployment name, and that AZURE_OPENAI_ENDPOINT "
                "and OPENAI_API_VERSION are correct."
            )
        if isinstance(exc, openai.RateLimitError):
            return LLMProviderError(
                f"Azure OpenAI rate limit or quota reached for deployment '{deployment}'. "
                "Wait a minute and retry."
            )
        if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)):
            return LLMProviderError(
                f"Could not reach Azure OpenAI at {endpoint}. Check your network and "
                "AZURE_OPENAI_ENDPOINT, then retry."
            )
        if isinstance(exc, openai.BadRequestError) and _error_field(exc, "code") == "content_filter":
            return LLMProviderError(
                "Azure OpenAI's content filter blocked the request. "
                "Review the transcript for content that may trigger the filter."
            )
        if isinstance(exc, openai.APIStatusError):
            message = _error_field(exc, "message") or exc.message
            return LLMProviderError(f"Azure OpenAI returned an error (HTTP {exc.status_code}): {message}")
        return LLMProviderError(f"The Azure OpenAI request failed: {exc}")


def _error_field(exc: openai.APIStatusError, name: str) -> str | None:
    """Read one field (message, code, type) from an API error body, if present."""
    body = exc.body
    if isinstance(body, dict):
        error = body.get("error", body)
        if isinstance(error, dict) and error.get(name):
            return str(error[name])
    return None
