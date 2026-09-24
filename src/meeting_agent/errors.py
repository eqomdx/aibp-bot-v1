"""Expected, user-facing errors.

Anything derived from MeetingAgentError is a problem the user can fix
(bad path, missing configuration, API outage). The CLI prints these as
one-line messages instead of tracebacks. Messages must never contain
secrets such as the API key.
"""


class MeetingAgentError(Exception):
    """Base class for expected errors with a human-readable message."""


class TranscriptError(MeetingAgentError):
    """The transcript could not be loaded or is not usable."""


class ConfigError(MeetingAgentError):
    """Required configuration is missing or invalid."""


class LLMProviderError(MeetingAgentError):
    """The LLM provider failed or returned nothing usable."""


class SummarisationError(MeetingAgentError):
    """The meeting service could not produce a summary."""


class ExtractionError(MeetingAgentError):
    """The model's structured item output could not be understood."""


class QuestionError(MeetingAgentError):
    """A question could not be asked or its answer could not be understood."""


class OutputError(MeetingAgentError):
    """A result could not be written to disk."""
