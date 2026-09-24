"""Structured project items: Actions, Decisions, Risks, Issues, Dependencies, Assumptions.

Defines the item shape, turns the model's JSON reply into items, merges
duplicates, and renders items as Markdown. Data and presentation are kept
separate: to_dict() is what goes to JSON (and later SharePoint);
items_to_markdown() is only for people.
"""

from dataclasses import dataclass

from meeting_agent.errors import ExtractionError
from meeting_agent.evidence import Evidence, parse_evidence
from meeting_agent.llm_output import load_json_reply, normalise_for_matching

ITEM_TYPES = ("Action", "Decision", "Risk", "Issue", "Dependency", "Assumption")
SECTION_HEADINGS = {
    "Action": "Actions",
    "Decision": "Decisions",
    "Risk": "Risks",
    "Issue": "Issues",
    "Dependency": "Dependencies",
    "Assumption": "Assumptions",
}
CONFIDENCE_LEVELS = ("High", "Medium", "Low")
NOT_STATED = "Not stated"

# Placeholder values models use for "not stated".
_NOT_STATED_VALUES = {
    "", "none", "null", "n/a", "na", "unknown", "unassigned", "tbc", "tbd",
    "not specified", "not stated", "no owner", "nobody", "no one",
}


@dataclass(frozen=True)
class ProjectItem:
    type: str
    description: str
    owner: str
    due_date: str
    source: Evidence
    confidence: str
    needs_pm_review: bool = False
    review_reasons: tuple[str, ...] = ()
    due_date_resolved: str | None = None  # ISO date, set by the application when safe

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "description": self.description,
            "owner": self.owner,
            "due_date": self.due_date,
            "due_date_resolved": self.due_date_resolved,
            "source": self.source.to_dict(),
            "confidence": self.confidence,
            "needs_pm_review": self.needs_pm_review,
            "review_reasons": list(self.review_reasons),
        }


def parse_project_items(text: str) -> list[ProjectItem]:
    """Parse the model's JSON reply into ProjectItems, or raise ExtractionError.

    Evidence is not checked here; see review.apply_review_checks().
    """
    data = load_json_reply(text, "item extraction", ExtractionError)

    raw_items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(raw_items, list):
        raise ExtractionError('The model reply has no "items" list.')

    return [_parse_item(raw, number) for number, raw in enumerate(raw_items, 1)]


def deduplicate(items: list[ProjectItem]) -> list[ProjectItem]:
    """Drop repeats of the same item: same type and same description, or same type and quote."""
    seen: set[tuple[str, str]] = set()
    unique = []
    for item in items:
        keys = {(item.type, "d:" + normalise_for_matching(item.description))}
        if item.source.quote:
            keys.add((item.type, "q:" + normalise_for_matching(item.source.quote)))
        if keys & seen:
            continue
        seen |= keys
        unique.append(item)
    return unique


def items_to_markdown(items: list[ProjectItem]) -> str:
    """Render items as Markdown: counts, one table per type, then items needing PM review."""
    flagged = sum(item.needs_pm_review for item in items)
    counts = ", ".join(
        f"{n} {SECTION_HEADINGS[t] if n != 1 else t}"
        for t in ITEM_TYPES
        if (n := sum(item.type == t for item in items))
    )
    lines = ["# Project Items", "", f"{len(items)} items{': ' + counts if counts else ''}. "
             f"{flagged} {'needs' if flagged == 1 else 'need'} PM review."]

    for item_type in ITEM_TYPES:
        lines += ["", f"## {SECTION_HEADINGS[item_type]}"]
        of_type = [item for item in items if item.type == item_type]
        if not of_type:
            lines.append("None identified.")
            continue
        lines += [
            "| # | Description | Owner | Due | Confidence | Source | PM review |",
            "|---|---|---|---|---|---|---|",
        ]
        for number, item in enumerate(of_type, 1):
            source = item.source.to_text() + ("" if item.source.verified else " (NOT VERIFIED)")
            cells = [str(number), item.description, item.owner, _due_text(item), item.confidence,
                     source, "Yes" if item.needs_pm_review else "No"]
            lines.append("| " + " | ".join(_cell(c) for c in cells) + " |")

    lines += ["", "## Needs PM Review"]
    if not flagged:
        lines.append("None identified.")
    for item_type in ITEM_TYPES:
        of_type = [item for item in items if item.type == item_type]
        for number, item in enumerate(of_type, 1):
            if item.needs_pm_review:
                lines.append(f"- **{item_type} {number}: {item.description}** {' '.join(item.review_reasons)}")

    return "\n".join(lines) + "\n"


def _parse_item(raw, number: int) -> ProjectItem:
    if not isinstance(raw, dict):
        raise ExtractionError(f"Item {number} is not a JSON object.")

    item_type = _canonical(raw.get("type"), ITEM_TYPES)
    if item_type is None:
        allowed = ", ".join(ITEM_TYPES)
        raise ExtractionError(
            f"Item {number} has type '{_text(raw.get('type'))}'. Allowed types: {allowed}."
        )

    description = _text(raw.get("description"))
    if not description:
        raise ExtractionError(f"Item {number} ({item_type}) has no description.")

    confidence = _canonical(raw.get("confidence"), CONFIDENCE_LEVELS)
    if confidence is None:
        raise ExtractionError(
            f"Item {number} ({item_type}) has confidence '{_text(raw.get('confidence'))}'. "
            "Expected High, Medium or Low."
        )

    model_flag = raw.get("needs_pm_review") is True
    reason = _text(raw.get("review_reason"))
    reasons = ((reason if reason.lower() not in _NOT_STATED_VALUES else "Flagged for review by the model."),) \
        if model_flag else ()

    return ProjectItem(
        type=item_type,
        description=description,
        owner=_or_not_stated(raw.get("owner")),
        due_date=_or_not_stated(raw.get("due_date")),
        source=parse_evidence(raw.get("source")),
        confidence=confidence,
        needs_pm_review=model_flag,
        review_reasons=reasons,
    )


def _canonical(value, allowed: tuple[str, ...]) -> str | None:
    """Match a value to an allowed spelling, ignoring case and surrounding space."""
    lookup = {option.lower(): option for option in allowed}
    return lookup.get(_text(value).lower())


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _or_not_stated(value) -> str:
    text = _text(value)
    return NOT_STATED if text.lower() in _NOT_STATED_VALUES else text


def _due_text(item: ProjectItem) -> str:
    if item.due_date_resolved and item.due_date_resolved != item.due_date:
        return f"{item.due_date} ({item.due_date_resolved})"
    return item.due_date


def _cell(text: str) -> str:
    """Make text safe for a Markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ")
