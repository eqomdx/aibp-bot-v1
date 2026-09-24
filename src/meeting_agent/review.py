"""PM review checks, applied in code after extraction (no LLM).

The team's original schema uses a four-state Review Flag: None, Missing,
Inferred, Ambiguous. The local bot also keeps human-readable review reasons.
Flags are recalculated here after de-duplication so record IDs and numbering
remain stable for the final batch.
"""

from dataclasses import replace
from datetime import date

from meeting_agent.dates import resolve_due_date
from meeting_agent.evidence import check_evidence
from meeting_agent.project_items import NOT_STATED, ProjectItem, REVIEW_FLAGS

MISSING_FIELD_REASONS = {
    "project": "Project is missing.",
    "meeting_date": "Meeting date is missing.",
    "owner": "No owner stated.",
}

LOW_CONFIDENCE_REASON = "Low confidence; confirm with the attendees."
SUGGESTED_OWNER_REASON = "Owner was inferred from context and is only a suggestion."

_FLAG_RANK = {"None": 0, "Inferred": 1, "Missing": 2, "Ambiguous": 3}


def apply_review_checks(
    items: list[ProjectItem],
    transcript: str,
    meeting_date: date | None = None,
    project: str | None = None,
) -> list[ProjectItem]:
    """Verify evidence, apply context, renumber, regenerate IDs and set review flags."""
    return [
        _review(item, transcript, meeting_date, project, number)
        for number, item in enumerate(items, 1)
    ]


def _review(
    item: ProjectItem,
    transcript: str,
    meeting_date: date | None,
    project: str | None,
    number: int,
) -> ProjectItem:
    source = check_evidence(item.source, transcript)

    final_project = (project or "").strip() or item.project
    final_meeting_date = meeting_date.isoformat() if meeting_date else item.meeting_date

    resolved, date_problem = (None, None)
    if item.due_date != NOT_STATED:
        # Resolve relative dates only when a trusted meeting date is known.
        context_date = meeting_date
        if context_date is None and final_meeting_date:
            try:
                context_date = date.fromisoformat(final_meeting_date)
            except ValueError:
                context_date = None
        resolved, date_problem = resolve_due_date(item.due_date, context_date)

    reasons = list(item.review_reasons)

    missing_reasons = []
    if not final_project:
        missing_reasons.append(MISSING_FIELD_REASONS["project"])
    if not final_meeting_date:
        missing_reasons.append(MISSING_FIELD_REASONS["meeting_date"])
    if item.type == "Action" and item.owner == NOT_STATED:
        missing_reasons.append(MISSING_FIELD_REASONS["owner"])
    reasons += missing_reasons

    suggested_owner = item.owner != NOT_STATED and item.owner.lower().endswith("(suggested)")
    if suggested_owner:
        reasons.append(SUGGESTED_OWNER_REASON)
    if item.confidence == "Low":
        reasons.append(LOW_CONFIDENCE_REASON)
    reasons += source.problems
    if date_problem:
        reasons.append(date_problem)

    reasons = list(dict.fromkeys(reasons))

    computed_flag = "None"
    if suggested_owner:
        computed_flag = _higher_flag(computed_flag, "Inferred")
    if missing_reasons:
        computed_flag = _higher_flag(computed_flag, "Missing")
    if source.problems or item.confidence == "Low" or date_problem:
        computed_flag = _higher_flag(computed_flag, "Ambiguous")
    if item.needs_pm_review and not reasons:
        computed_flag = _higher_flag(computed_flag, "Ambiguous")

    model_flag = item.review_flag if item.review_flag in REVIEW_FLAGS else "None"
    final_flag = _higher_flag(computed_flag, model_flag)

    # If the model supplied only a generic review reason, keep the item reviewable.
    if reasons and final_flag == "None":
        final_flag = "Ambiguous"

    record_id = f"{final_project or 'null'}-{number}"
    return replace(
        item,
        record_id=record_id,
        number=number,
        project=final_project,
        meeting_date=final_meeting_date,
        source=source,
        due_date_resolved=resolved.isoformat() if resolved else None,
        review_flag=final_flag,
        needs_pm_review=final_flag != "None",
        review_reasons=tuple(reasons),
    )


def _higher_flag(left: str, right: str) -> str:
    """Return the higher-priority flag using Ambiguous > Missing > Inferred > None."""
    return left if _FLAG_RANK[left] >= _FLAG_RANK[right] else right
