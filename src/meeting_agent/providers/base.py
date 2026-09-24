"""The interface every LLM provider implements.

MeetingService depends only on this. Swapping Azure OpenAI for another
deployment, a Copilot Studio agent or an internal API means writing a new
class with this method, not changing meeting logic.
"""

from typing import Protocol


class LLMProvider(Protocol):
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Return the model's text reply.

        Implementations raise LLMProviderError on failure or empty output.
        """
        ...
