"""Missing-information checks on extracted project items.

Deterministic rules, no LLM: flags what a project manager would need to
chase after the meeting, such as an action with no owner or due date.
"""

from dataclasses import asdict, dataclass

from meeting_agent.project_items import ProjectItem

# Fields each item type needs before it can be tracked.
REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "action": ("owner", "due_date"),
    "risk": ("owner",),
    "issue": ("owner",),
    "dependency": ("owner",),
}

GAP_MESSAGES = {
    "owner": "No owner stated.",
    "due_date": "No due date stated.",
    "source": "Source quote not found in the transcript; check this item is real.",
    "confidence": "Low confidence; confirm with the attendees.",
}


@dataclass(frozen=True)
class InformationGap:
    item_number: int  # 1-based position in the items list
    item_type: str
    item_description: str
    gap: str  # a key of GAP_MESSAGES
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


def find_missing_information(items: list[ProjectItem]) -> list[InformationGap]:
    """Return every gap across the items, in item order."""
    gaps = []
    for number, item in enumerate(items, 1):
        for gap in _gaps_for(item):
            gaps.append(
                InformationGap(
                    item_number=number,
                    item_type=item.type,
                    item_description=item.description,
                    gap=gap,
                    message=GAP_MESSAGES[gap],
                )
            )
    return gaps


def gaps_to_markdown(gaps: list[InformationGap]) -> str:
    """Render gaps as a Markdown section, grouped by item."""
    lines = ["## Missing Information"]
    if not gaps:
        return "\n".join(lines + ["None identified."]) + "\n"

    by_item: dict[int, list[InformationGap]] = {}
    for gap in gaps:
        by_item.setdefault(gap.item_number, []).append(gap)

    for item_gaps in by_item.values():
        first = item_gaps[0]
        label = first.item_type.capitalize()
        problems = " ".join(gap.message for gap in item_gaps)
        lines.append(f"- **{label}: {first.item_description}** {problems}")
    return "\n".join(lines) + "\n"


def _gaps_for(item: ProjectItem) -> list[str]:
    gaps = [field for field in REQUIRED_FIELDS.get(item.type, ()) if not getattr(item, field)]
    if not item.source_verified:
        gaps.append("source")
    if item.confidence == "low":
        gaps.append("confidence")
    return gaps
