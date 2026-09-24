import pytest

from meeting_agent.meeting_service import MeetingService
from meeting_agent.missing_information import (
    GAP_MESSAGES,
    InformationGap,
    find_missing_information,
    gaps_to_markdown,
)
from meeting_agent.project_items import ProjectItem


def make_item(type="action", owner="Annie", due_date="Friday", verified=True, confidence="high",
              description="Do the thing."):
    return ProjectItem(
        type=type,
        description=description,
        owner=owner,
        due_date=due_date,
        source="quoted words",
        confidence=confidence,
        source_verified=verified,
    )


def gap_codes(item):
    return [gap.gap for gap in find_missing_information([item])]


def test_complete_action_has_no_gaps():
    assert gap_codes(make_item()) == []


def test_action_needs_owner_and_due_date():
    assert gap_codes(make_item(owner=None, due_date=None)) == ["owner", "due_date"]


@pytest.mark.parametrize("item_type", ["risk", "issue", "dependency"])
def test_raid_items_need_an_owner_but_not_a_due_date(item_type):
    assert gap_codes(make_item(type=item_type, owner=None, due_date=None)) == ["owner"]


@pytest.mark.parametrize("item_type", ["decision", "assumption"])
def test_decisions_and_assumptions_need_no_owner_or_date(item_type):
    assert gap_codes(make_item(type=item_type, owner=None, due_date=None)) == []


def test_unverified_source_is_flagged_for_any_type():
    assert gap_codes(make_item(type="decision", verified=False)) == ["source"]


def test_low_confidence_is_flagged():
    assert gap_codes(make_item(confidence="low")) == ["confidence"]
    assert gap_codes(make_item(confidence="medium")) == []


def test_gaps_reference_their_item_by_position():
    items = [make_item(), make_item(type="issue", owner=None, description="No transcript yet.")]

    (gap,) = find_missing_information(items)

    assert gap == InformationGap(
        item_number=2,
        item_type="issue",
        item_description="No transcript yet.",
        gap="owner",
        message=GAP_MESSAGES["owner"],
    )


def test_gap_dict_is_json_ready():
    (gap,) = find_missing_information([make_item(due_date=None)])

    assert gap.to_dict() == {
        "item_number": 1,
        "item_type": "action",
        "item_description": "Do the thing.",
        "gap": "due_date",
        "message": "No due date stated.",
    }


def test_markdown_groups_gaps_by_item():
    gaps = find_missing_information([
        make_item(owner=None, due_date=None, description="Have the demo ready."),
        make_item(type="issue", owner=None, description="No sample transcript."),
    ])

    assert gaps_to_markdown(gaps) == (
        "## Missing Information\n"
        "- **Action: Have the demo ready.** No owner stated. No due date stated.\n"
        "- **Issue: No sample transcript.** No owner stated.\n"
    )


def test_markdown_with_no_gaps():
    assert gaps_to_markdown([]) == "## Missing Information\nNone identified.\n"


def test_available_through_meeting_service(fake_provider):
    provider = fake_provider()

    gaps = MeetingService(provider).find_missing_information([make_item(owner=None)])

    assert gaps[0].gap == "owner"
    assert provider.calls == []  # rule-based: no LLM call
