"""Evidence: where in the transcript a piece of information came from.

The model supplies speaker, quote and (only if the transcript has them)
timestamp. The application then checks all three against the transcript,
so a fabricated quote, speaker or timestamp is caught in code.
"""

from dataclasses import dataclass, replace

from meeting_agent.llm_output import quote_in_text

_NOT_STATED = {"", "none", "null", "n/a", "na", "unknown", "not stated", "not available"}


@dataclass(frozen=True)
class Evidence:
    speaker: str | None
    quote: str
    timestamp: str | None = None
    # Set by check_evidence(), not the model.
    verified: bool = False
    problems: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "speaker": self.speaker,
            "quote": self.quote,
            "timestamp": self.timestamp,
            "verified": self.verified,
        }

    def to_text(self) -> str:
        who = self.speaker or "Unknown speaker"
        when = f" ({self.timestamp})" if self.timestamp else ""
        return f'{who}{when}: "{self.quote}"'


def parse_evidence(raw) -> Evidence:
    """Build Evidence from the model's source field (an object, or a bare quote string)."""
    if isinstance(raw, dict):
        return Evidence(
            speaker=_optional(raw.get("speaker")),
            quote=_optional(raw.get("quote")) or "",
            timestamp=_optional(raw.get("timestamp")),
        )
    if isinstance(raw, str):
        return Evidence(speaker=None, quote=raw.strip())
    return Evidence(speaker=None, quote="")


def check_evidence(evidence: Evidence, transcript: str) -> Evidence:
    """Return the evidence with `verified` and `problems` set from the transcript."""
    problems = []
    if not evidence.quote:
        problems.append("No source quote given.")
    elif not quote_in_text(evidence.quote, transcript):
        problems.append("Source quote not found in the transcript.")
    if evidence.speaker and not quote_in_text(evidence.speaker, transcript):
        problems.append(f"Speaker '{evidence.speaker}' not found in the transcript.")
    if evidence.timestamp and not quote_in_text(evidence.timestamp, transcript):
        problems.append(f"Timestamp '{evidence.timestamp}' not found in the transcript.")
    return replace(evidence, verified=not problems, problems=tuple(problems))


def _optional(value) -> str | None:
    text = "" if value is None else str(value).strip()
    return None if text.lower() in _NOT_STATED else text
