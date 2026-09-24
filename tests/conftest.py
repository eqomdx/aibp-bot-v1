"""Shared test helpers. Nothing here touches the network."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from meeting_agent.config import AzureOpenAISettings
from meeting_agent.prompts import EXTRACTION_SYSTEM_PROMPT, QA_SYSTEM_PROMPT

# openai 3.x ships on httpx2; older 1.x releases used httpx. Accept either.
try:
    import httpx2 as httpx
except ImportError:  # pragma: no cover
    import httpx

# Obviously fake. Tests assert this never appears in any error message.
FAKE_API_KEY = "fake-key-DO-NOT-LEAK-0123456789"

APP_ENV_VARS = (
    "LLM_PROVIDER",
    "AZURE_OPENAI_ENDPOINT",
    "OPENAI_API_KEY",
    "OPENAI_API_VERSION",
    "CHAT_MODEL",
    "EMBEDDING_MODEL",
)


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    """Keep the developer's real .env settings out of every test."""
    for name in APP_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def azure_env(monkeypatch):
    """A complete, fake Azure configuration in the environment."""
    values = {
        "AZURE_OPENAI_ENDPOINT": "https://test-resource.cognitiveservices.azure.com/",
        "OPENAI_API_KEY": FAKE_API_KEY,
        "OPENAI_API_VERSION": "2024-12-01-preview",
        "CHAT_MODEL": "test-deployment",
        "EMBEDDING_MODEL": "test-embeddings",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return values


@pytest.fixture
def settings():
    return AzureOpenAISettings(
        endpoint="https://test-resource.cognitiveservices.azure.com/",
        api_key=FAKE_API_KEY,
        api_version="2024-12-01-preview",
        chat_deployment="test-deployment",
    )


class FakeProvider:
    """An LLMProvider that records prompts and returns canned replies.

    `items_reply` answers extraction requests, `answer_reply` answers questions,
    and `reply` answers everything else (summaries).
    """

    DEFAULT_ANSWER = '{"category": "not_in_transcript", "answer": "", "sources": []}'

    def __init__(self, reply="# Meeting Summary", items_reply='{"items": []}', answer_reply=DEFAULT_ANSWER):
        self.reply = reply
        self.items_reply = items_reply
        self.answer_reply = answer_reply
        self.calls = []

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        if system_prompt == EXTRACTION_SYSTEM_PROMPT:
            return self.items_reply
        if system_prompt == QA_SYSTEM_PROMPT:
            return self.answer_reply
        return self.reply


@pytest.fixture
def fake_provider():
    """Factory: fake_provider(reply=..., items_reply=..., answer_reply=...) -> FakeProvider."""
    return FakeProvider


SAMPLE_TRANSCRIPT_PATH = Path(__file__).resolve().parents[1] / "transcript.md"


def summary_headings(markdown: str) -> list[str]:
    """The Markdown headings (lines starting with #) in order."""
    return [line.strip() for line in markdown.splitlines() if line.startswith("#")]


def chat_response(content, finish_reason="stop"):
    """Shape-alike of an SDK ChatCompletion with one choice."""
    message = SimpleNamespace(content=content, role="assistant")
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish_reason)])


@pytest.fixture
def api_request():
    """A dummy HTTP request, needed to construct openai exception objects."""
    return httpx.Request("POST", "https://test-resource.cognitiveservices.azure.com/openai/")


@pytest.fixture
def status_error(api_request):
    """Factory: status_error(openai.NotFoundError, 404, "msg", code="...") -> exception."""

    def make(cls, status, message="boom", code=None):
        response = httpx.Response(status, request=api_request)
        body = {"error": {"message": message, "code": code}}
        return cls(message, response=response, body=body)

    return make
