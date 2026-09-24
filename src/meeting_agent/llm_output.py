"""Helpers for handling model output: reading JSON replies and checking quotes.

Shared by every feature that asks the model for structured, quoted output
(item extraction, question answering).
"""

import json
import re

from meeting_agent.errors import MeetingAgentError


def load_json_reply(text: str, purpose: str, error_cls: type[MeetingAgentError]):
    """Parse a model's JSON reply, tolerating a Markdown code fence around it.

    `purpose` names the request in error messages (e.g. "item extraction").
    """
    cleaned = (text or "").strip()
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        cleaned = fence.group(1)
    if not cleaned:
        raise error_cls(f"The model returned an empty response for {purpose}.")
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise error_cls(
            f"The model reply for {purpose} was not valid JSON ({exc.msg} at line {exc.lineno})."
        ) from None


def normalise_for_matching(text: str) -> str:
    """Lower-case, straighten quotes and collapse whitespace for quote matching."""
    text = text.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
    return " ".join(text.lower().split())


def quote_in_text(quote: str, text: str) -> bool:
    """True if `quote` is non-empty and appears in `text`, ignoring case, spacing and quote style."""
    quote = normalise_for_matching(quote or "")
    return bool(quote) and quote in normalise_for_matching(text)
