"""Validate an extraction produced elsewhere (for example by Copilot Studio).

This is the governance path: another system's model proposes project items,
and this module checks them against the original transcript using the same
deterministic logic as the local extraction path. It makes no LLM call and
needs no credentials. It never imports a provider.

    parse -> deduplicate -> verify evidence, resolve dates, flag, renumber, re-ID
"""

import json
from datetime import date
from typing import Any

from meeting_agent.errors import ExtractionError, MeetingDateError
from meeting_agent.project_items import build_extraction_summary, deduplicate, parse_project_items
from meeting_agent.review import apply_review_checks
from meeting_agent.transcript import detect_meeting_date, validate_transcript


def validate_extraction(
    transcript: str,
    extraction: dict[str, Any] | list[Any] | str,
    project: str | None = None,
    meeting_date: date | None = None,
) -> dict[str, Any]:
    """Check AI-extracted items against the transcript and return clean RAID JSON.

    `extraction` is the extraction JSON as an object ({"items": [...]}), a bare
    list of items, or the model's raw text reply (code fences are tolerated).
    If `meeting_date` is not given, a "Date: YYYY-MM-DD" line at the top of the
    transcript is used when present.

    Raises TranscriptError for an unusable transcript and ExtractionError for an
    extraction that does not match the schema.
    """
    validate_transcript(transcript or "")

    text = extraction if isinstance(extraction, str) else _to_json(extraction)
    items = deduplicate(parse_project_items(text))

    project = (project or "").strip() or None
    meeting_date = meeting_date or detect_meeting_date(transcript)
    items = apply_review_checks(items, transcript, meeting_date, project)

    return {
        "meetingSummary": build_extraction_summary(items),
        "project": project,
        "meeting_date": meeting_date.isoformat() if meeting_date else None,
        "items": [item.to_dict() for item in items],
    }


def parse_meeting_date(text: str | None) -> date | None:
    """Parse an optional YYYY-MM-DD meeting date; blank means none. Raises MeetingDateError."""
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    try:
        return date.fromisoformat(cleaned)
    except ValueError:
        raise MeetingDateError(f"meeting_date '{text}' is not a valid date in YYYY-MM-DD form.") from None


def _to_json(extraction: Any) -> str:
    try:
        return json.dumps(extraction)
    except (TypeError, ValueError):
        raise ExtractionError("The extraction could not be read as JSON.") from None
