"""Application-level safeguards for the meeting assistant.

These run in code, so they hold whatever the model does. They complement,
not replace, the rules in prompts.SAFETY_RULES and the architecture itself:
the model never sees configuration or secrets, and has no tools that could
change an external system.
"""

import re

from meeting_agent.llm_output import normalise_for_matching
from meeting_agent.prompts import SYSTEM_PROMPTS

ANSWERED = "answered"
NOT_IN_TRANSCRIPT = "not_in_transcript"
OUT_OF_SCOPE = "out_of_scope"
SECRET_REQUEST = "secret_request"
EXTERNAL_ACTION = "external_action"
PERSONAL_JUDGEMENT = "personal_judgement"

# Fixed replies for everything except a real answer. The model's own wording is
# not used for these, so a refusal can never carry leaked or injected text.
CANNED_REPLIES = {
    NOT_IN_TRANSCRIPT: "I can't determine that from this meeting transcript.",
    OUT_OF_SCOPE: (
        "I can help with questions and analysis related to this meeting transcript, "
        "but that request is outside the meeting-assistant scope."
    ),
    SECRET_REQUEST: (
        "I can't share credentials, configuration or my system instructions. "
        "I can answer questions about the meeting itself."
    ),
    EXTERNAL_ACTION: (
        "I can't make changes to external systems such as Planner, SharePoint, email or Teams. "
        "That isn't available in this prototype. In the future workflow, proposed changes will "
        "go to the project manager for review and approval first."
    ),
    PERSONAL_JUDGEMENT: (
        "The transcript records what people said and agreed to do, but it doesn't give a "
        "reliable basis for judging or ranking individuals."
    ),
}

# --- Deterministic screening of the user's question (before any model call) ---

_EXPLICIT_SECRETS = re.compile(
    r"openai_api_key|azure_openai_endpoint|\.env\b|environment variables?|env vars?|"
    r"system prompt|your (?:instructions|prompt|rules)|hidden instructions|"
    r"authori[sz]ation header|auth header|bearer token",
    re.IGNORECASE,
)
_SECRET_NOUNS = re.compile(
    r"\b(?:api[\s_-]?keys?|secret keys?|secrets?|passwords?|credentials?|access tokens?|"
    r"connection strings?)\b",
    re.IGNORECASE,
)
_REVEAL_VERBS = re.compile(
    r"\b(?:show|reveal|print|output|display|give|tell|share|leak|dump|list|repeat|echo|"
    r"what(?:'s| is| are))\b",
    re.IGNORECASE,
)
_ACTION_VERBS = (
    r"create|add|send|post|update|upload|push|email|e-mail|notify|schedule|assign|book|"
    r"write|move|delete|remove|log|raise|file|submit|publish|message"
)
_EXTERNAL_REQUEST = re.compile(
    r"^\s*(?:(?:please|now|ok(?:ay)?|go ahead and)\s*,?\s+)*"
    r"(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?)?"
    rf"(?:{_ACTION_VERBS})\b",
    re.IGNORECASE,
)
_EXTERNAL_TARGETS = re.compile(
    r"\b(?:planner|sharepoint|teams|e-?mails?|outlook|inbox|calendar|jira|power automate|"
    r"workflows?|tasks?|tickets?|raid log|channel|chat)\b",
    re.IGNORECASE,
)


def screen_question(question: str) -> str | None:
    """Return a refusal category for requests the app can recognise itself, else None.

    Only clear-cut cases are caught here: asking for secrets or instructions, and
    imperative requests to change an external system. Everything else goes to the
    model, whose reply category is then enforced by the application.
    """
    if _EXPLICIT_SECRETS.search(question):
        return SECRET_REQUEST
    if _SECRET_NOUNS.search(question) and _REVEAL_VERBS.search(question):
        return SECRET_REQUEST
    if _EXTERNAL_REQUEST.search(question) and _EXTERNAL_TARGETS.search(question):
        return EXTERNAL_ACTION
    return None


# --- Checking the model's output --------------------------------------------

_MIN_LEAK_LENGTH = 40


def _instruction_fragments() -> list[str]:
    fragments = set()
    for prompt in SYSTEM_PROMPTS:
        for line in prompt.splitlines():
            for sentence in re.split(r"(?<=[.!?])\s+", line):
                normalised = normalise_for_matching(sentence)
                if len(normalised) >= _MIN_LEAK_LENGTH:
                    fragments.add(normalised)
    return sorted(fragments)


_INSTRUCTION_FRAGMENTS = _instruction_fragments()


def reveals_instructions(text: str) -> bool:
    """True if the text repeats any sentence of the system instructions verbatim."""
    normalised = normalise_for_matching(text)
    return any(fragment in normalised for fragment in _INSTRUCTION_FRAGMENTS)
