"""PM review checks, applied in code after extraction (no LLM).

Context-sensitive: each item type is held only to what it needs. A Decision
with no owner is normal; an Action with no owner is not. The model can also
flag items for reasons only it can see (ambiguity, contradictions, a deadline
that seems necessary); those reasons are kept alongside the rule-based ones.
"""

from dataclasses import replace
from datetime import date

from meeting_agent.dates import resolve_due_date
from meeting_agent.evidence import check_evidence
from meeting_agent.project_items import NOT_STATED, ProjectItem

# Fields each item type must have. Edit this table to change what gets flagged.
REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "Action": ("owner",),
}

MISSING_FIELD_REASONS = {
    "owner": "No owner stated.",
    "due_date": "No due date stated.",
}

LOW_CONFIDENCE_REASON = "Low confidence; confirm with the attendees."


def apply_review_checks(
    items: list[ProjectItem], transcript: str, meeting_date: date | None = None
) -> list[ProjectItem]:
    """Verify evidence, resolve relative due dates, and set needs_pm_review with reasons."""
    return [_review(item, transcript, meeting_date) for item in items]


def _review(item: ProjectItem, transcript: str, meeting_date: date | None) -> ProjectItem:
    source = check_evidence(item.source, transcript)

    resolved, date_problem = (None, None)
    if item.due_date != NOT_STATED:
        resolved, date_problem = resolve_due_date(item.due_date, meeting_date)

    reasons = list(item.review_reasons)
    reasons += [
        MISSING_FIELD_REASONS[field]
        for field in REQUIRED_FIELDS.get(item.type, ())
        if getattr(item, field) == NOT_STATED
    ]
    if item.confidence == "Low":
        reasons.append(LOW_CONFIDENCE_REASON)
    reasons += source.problems
    if date_problem:
        reasons.append(date_problem)

    reasons = list(dict.fromkeys(reasons))  # drop repeats, keep order
    return replace(
        item,
        source=source,
        due_date_resolved=resolved.isoformat() if resolved else None,
        needs_pm_review=bool(reasons),
        review_reasons=tuple(reasons),
    )
