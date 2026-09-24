"""Structured project items (actions, decisions, RAID, dependencies, assumptions).

Defines the item shape, turns model output into items, checks each item's
source quote against the transcript, and renders items as Markdown. Knows
nothing about which LLM produced the text.
"""

from dataclasses import asdict, dataclass, replace

from meeting_agent.errors import ExtractionError
from meeting_agent.llm_output import load_json_reply, quote_in_text

# Item types in display order, with their Markdown section headings.
ITEM_TYPES = {
    "action": "Actions",
    "decision": "Decisions",
    "risk": "Risks",
    "issue": "Issues",
    "dependency": "Dependencies",
    "assumption": "Assumptions",
}

CONFIDENCE_LEVELS = ("high", "medium", "low")

# Placeholder values models use for "not stated"; stored as None.
_NOT_STATED = {"", "none", "null", "n/a", "na", "unknown", "unassigned", "tbc", "tbd", "not specified", "not stated"}


@dataclass(frozen=True)
class ProjectItem:
    type: str
    description: str
    owner: str | None
    due_date: str | None
    source: str
    confidence: str
    # Set by the application, not the model: was `source` found in the transcript?
    source_verified: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def parse_project_items(text: str) -> list[ProjectItem]:
    """Parse the model's JSON reply into ProjectItems, or raise ExtractionError."""
    data = load_json_reply(text, "item extraction", ExtractionError)

    raw_items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(raw_items, list):
        raise ExtractionError('The model reply has no "items" list.')

    return [_parse_item(raw, number) for number, raw in enumerate(raw_items, 1)]


def verify_sources(items: list[ProjectItem], transcript: str) -> list[ProjectItem]:
    """Return items with source_verified set by checking each quote against the transcript."""
    return [replace(item, source_verified=quote_in_text(item.source, transcript)) for item in items]


def items_to_markdown(items: list[ProjectItem]) -> str:
    """Render items as Markdown tables, one section per type, in a fixed order."""
    lines = ["# Project Items"]
    unverified = sum(not item.source_verified for item in items)
    if unverified:
        lines += ["", f"> **{unverified} item(s) cite a source that was not found in the transcript.** "
                      "Check these before relying on them."]

    for item_type, heading in ITEM_TYPES.items():
        lines += ["", f"## {heading}"]
        of_type = [item for item in items if item.type == item_type]
        if not of_type:
            lines.append("None identified.")
            continue
        lines += [
            "| Description | Owner | Due | Confidence | Source |",
            "|---|---|---|---|---|",
        ]
        for item in of_type:
            source = f'"{item.source}"' if item.source_verified else f'"{item.source}" (NOT FOUND IN TRANSCRIPT)'
            cells = [item.description, item.owner or "Not stated", item.due_date or "Not stated",
                     item.confidence, source]
            lines.append("| " + " | ".join(_cell(c) for c in cells) + " |")

    return "\n".join(lines) + "\n"


def _parse_item(raw, number: int) -> ProjectItem:
    if not isinstance(raw, dict):
        raise ExtractionError(f"Item {number} is not a JSON object.")

    item_type = _text(raw.get("type")).lower()
    if item_type not in ITEM_TYPES:
        allowed = ", ".join(ITEM_TYPES)
        raise ExtractionError(f"Item {number} has unknown type '{item_type}'. Expected one of: {allowed}.")

    description = _text(raw.get("description"))
    if not description:
        raise ExtractionError(f"Item {number} ({item_type}) has no description.")

    confidence = _text(raw.get("confidence")).lower()
    if confidence not in CONFIDENCE_LEVELS:
        raise ExtractionError(
            f"Item {number} ({item_type}) has confidence '{confidence}'. Expected high, medium or low."
        )

    return ProjectItem(
        type=item_type,
        description=description,
        owner=_optional(raw.get("owner")),
        due_date=_optional(raw.get("due_date")),
        source=_text(raw.get("source")),
        confidence=confidence,
    )


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _optional(value) -> str | None:
    text = _text(value)
    return None if text.lower() in _NOT_STATED else text


def _cell(text: str) -> str:
    """Make text safe for a Markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ")
