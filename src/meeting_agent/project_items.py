"""Structured project items: Actions, Decisions, Risks, Issues, Dependencies, Assumptions.

The public JSON shape mirrors the team's original RAID schema so it can later
feed Power Automate / SharePoint without another translation layer. A few
internal fields (verified source, confidence and review reasons) are retained
as extensions because they are useful for QA and PM review.
"""

from dataclasses import dataclass
from datetime import date

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
STATUS_VALUES = ("Open", "Closed", "Blocked", "In Progress", "Monitoring")
REVIEW_FLAGS = ("None", "Missing", "Inferred", "Ambiguous")
NOT_STATED = "Not stated"

# Placeholder values models use for "not stated".
_NOT_STATED_VALUES = {
    "", "none", "null", "n/a", "na", "unknown", "unassigned", "tbc", "tbd",
    "not specified", "not stated", "no owner", "nobody", "no one",
}


@dataclass(frozen=True)
class ProjectItem:
    # Original RAID / downstream fields.
    record_id: str
    number: int
    project: str | None
    meeting_date: str | None
    type: str
    title: str
    description: str
    owner: str
    due_date: str
    status: str
    priority: str | None
    impact: str | None
    likelihood: str | None
    mitigation_next_step: str | None
    decision_rationale: str | None
    source: Evidence
    review_flag: str
    reviewer_notes: str | None

    # QA / review extensions retained from the local bot.
    confidence: str
    needs_pm_review: bool = False
    review_reasons: tuple[str, ...] = ()
    due_date_resolved: str | None = None

    def to_dict(self) -> dict:
        """Return the JSON record used by downstream automation.

        The original fields appear first and keep their original names. The
        final extension fields are intentionally additive so existing QA and
        local review tooling still has source verification and diagnostics.
        """
        due_date = self.due_date_resolved
        if due_date is None and _looks_like_iso_date(self.due_date):
            due_date = self.due_date

        return {
            "record_id": self.record_id,
            "number": self.number,
            "project": self.project,
            "meeting_date": self.meeting_date,
            "type": self.type,
            "title": self.title,
            "description": self.description,
            "owner": None if self.owner == NOT_STATED else self.owner,
            "due_date": due_date,
            "status": self.status,
            "priority": self.priority,
            "impact": self.impact,
            "likelihood": self.likelihood,
            "mitigation_next_step": self.mitigation_next_step,
            "decision_rationale": self.decision_rationale,
            "source_evidence": self.source.to_text(),
            "review_flag": self.review_flag,
            "reviewer_notes": self.reviewer_notes,
            # Local-bot extensions.
            "due_date_text": None if self.due_date == NOT_STATED else self.due_date,
            "source": self.source.to_dict(),
            "confidence": self.confidence,
            "needs_pm_review": self.needs_pm_review,
            "review_reasons": list(self.review_reasons),
        }


def parse_project_items(text: str) -> list[ProjectItem]:
    """Parse the model's JSON reply into ProjectItems, or raise ExtractionError.

    Record IDs and final review flags are recalculated by review.apply_review_checks()
    after de-duplication, so numbering stays sequential even when duplicates are removed.
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


def build_extraction_summary(items: list[ProjectItem]) -> str:
    """Create the original top-level meetingSummary field without another model call."""
    flagged = sum(item.review_flag != "None" for item in items)
    counts = ", ".join(
        f"{n} {SECTION_HEADINGS[t] if n != 1 else t}"
        for t in ITEM_TYPES
        if (n := sum(item.type == t for item in items))
    )
    first_titles = "; ".join(item.title for item in items[:3] if item.title)
    first = f"Extracted {len(items)} project items" + (f" ({counts})" if counts else "") + "."
    second = f"{flagged} {'has' if flagged == 1 else 'have'} an outstanding Review Flag."
    if first_titles:
        first = f"{first[:-1]} covering {first_titles}."
    return f"{first} {second}"


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
            "| # | Record ID | Title | Description | Owner | Due | Status | Priority | Review Flag | Source |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for item in of_type:
            source = item.source.to_text() + ("" if item.source.verified else " (NOT VERIFIED)")
            cells = [
                str(item.number), item.record_id, item.title, item.description, item.owner, _due_text(item),
                item.status, item.priority or "", item.review_flag, source,
            ]
            lines.append("| " + " | ".join(_cell(c) for c in cells) + " |")

    lines += ["", "## Needs PM Review"]
    if not flagged:
        lines.append("None identified.")
    for item in items:
        if item.needs_pm_review:
            reason = " ".join(item.review_reasons) or f"Review Flag: {item.review_flag}."
            lines.append(f"- **{item.record_id} — {item.title}** {reason}")

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

    title = _text(raw.get("title")) or _default_title(description)

    confidence = _canonical(raw.get("confidence"), CONFIDENCE_LEVELS)
    if confidence is None:
        raise ExtractionError(
            f"Item {number} ({item_type}) has confidence '{_text(raw.get('confidence'))}'. "
            "Expected High, Medium or Low."
        )

    status = _canonical(raw.get("status"), STATUS_VALUES) or "Open"

    model_flag = raw.get("needs_pm_review") is True
    reason = _text(raw.get("review_reason"))
    reasons = ((reason if reason.lower() not in _NOT_STATED_VALUES else "Flagged for review by the model."),) \
        if model_flag else ()

    review_flag = _canonical(raw.get("review_flag"), REVIEW_FLAGS) or ("Ambiguous" if model_flag else "None")
    project = _nullable(raw.get("project"))
    meeting_date = _normalise_iso_or_none(raw.get("meeting_date"))
    owner = _or_not_stated(raw.get("owner"))
    due_date = _or_not_stated(raw.get("due_date"))

    # Original schema requires generated IDs. We regenerate after de-duplication too.
    record_id = f"{project or 'null'}-{number}"

    return ProjectItem(
        record_id=record_id,
        number=number,
        project=project,
        meeting_date=meeting_date,
        type=item_type,
        title=title,
        description=description,
        owner=owner,
        due_date=due_date,
        status=status,
        priority=_nullable(raw.get("priority")),
        impact=_nullable(raw.get("impact")) if item_type in ("Risk", "Issue") else None,
        likelihood=_nullable(raw.get("likelihood")) if item_type == "Risk" else None,
        mitigation_next_step=_nullable(raw.get("mitigation_next_step")),
        decision_rationale=_nullable(raw.get("decision_rationale")) if item_type == "Decision" else None,
        source=parse_evidence(raw.get("source") or raw.get("source_evidence")),
        review_flag=review_flag,
        reviewer_notes=_nullable(raw.get("reviewer_notes")),
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


def _nullable(value) -> str | None:
    text = _text(value)
    return None if text.lower() in _NOT_STATED_VALUES else text


def _or_not_stated(value) -> str:
    return _nullable(value) or NOT_STATED


def _normalise_iso_or_none(value) -> str | None:
    text = _nullable(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _looks_like_iso_date(value: str) -> bool:
    if value == NOT_STATED:
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _default_title(description: str) -> str:
    one_line = " ".join(description.split())
    return one_line if len(one_line) <= 80 else one_line[:77].rstrip() + "..."


def _due_text(item: ProjectItem) -> str:
    if item.due_date_resolved and item.due_date_resolved != item.due_date:
        return f"{item.due_date} ({item.due_date_resolved})"
    return item.due_date


def _cell(text: str) -> str:
    """Make text safe for a Markdown table cell."""
    return str(text).replace("|", "\\|").replace("\n", " ")
