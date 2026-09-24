"""Phase 2: parsing, validation, review flags, duplicates and rendering of project items."""

import json
from datetime import date

import pytest

from meeting_agent.errors import ExtractionError
from meeting_agent.evidence import Evidence, check_evidence, parse_evidence
from meeting_agent.project_items import (
    CONFIDENCE_LEVELS,
    ITEM_TYPES,
    NOT_STATED,
    deduplicate,
    items_to_markdown,
    parse_project_items,
)
from meeting_agent.review import LOW_CONFIDENCE_REASON, apply_review_checks

TRANSCRIPT = """\
10:01 Kat: We need to have the demo ready for Friday.
10:02 Annie: I'll investigate   whether the system can detect a transcript automatically.
10:03 Izzy: I’ll ask Chloe for one.
10:04 Kat: Maybe Chloe could send us the RAID document.
"""


def raw(**overrides):
    base = {
        "type": "Action",
        "description": "Investigate automatic transcript detection.",
        "owner": "Annie",
        "due_date": "Not stated",
        "source": {"speaker": "Annie", "quote": "I'll investigate whether the system", "timestamp": "10:02"},
        "confidence": "High",
        "needs_pm_review": False,
        "review_reason": None,
    }
    return {**base, **overrides}


def reply(*items):
    return json.dumps({"items": list(items)})


def extract(*items, meeting_date=None):
    """Parse, deduplicate and review, as MeetingService.extract_items does."""
    return apply_review_checks(deduplicate(parse_project_items(reply(*items))), TRANSCRIPT, meeting_date)


# --- parsing and validation ----------------------------------------------

def test_item_has_the_specified_fields():
    (item,) = extract(raw())

    assert list(item.to_dict()) == [
        "type", "description", "owner", "due_date", "due_date_resolved",
        "source", "confidence", "needs_pm_review", "review_reasons",
    ]
    assert item.to_dict()["source"] == {
        "speaker": "Annie", "quote": "I'll investigate whether the system", "timestamp": "10:02", "verified": True,
    }


def test_all_six_types_are_accepted():
    items = parse_project_items(reply(*(raw(type=t, description=t) for t in ITEM_TYPES)))

    assert [i.type for i in items] == list(ITEM_TYPES)


@pytest.mark.parametrize(("given", "stored"), [("action", "Action"), (" RISK ", "Risk"), ("decision", "Decision")])
def test_type_spelling_is_normalised(given, stored):
    assert parse_project_items(reply(raw(type=given)))[0].type == stored


@pytest.mark.parametrize("bad_type", ["Milestone", "Task", "Question", ""])
def test_invented_types_are_rejected(bad_type):
    with pytest.raises(ExtractionError, match="Allowed types: Action, Decision, Risk, Issue, Dependency, Assumption"):
        parse_project_items(reply(raw(type=bad_type)))


@pytest.mark.parametrize(("given", "stored"), [("high", "High"), ("MEDIUM", "Medium"), ("Low", "Low")])
def test_confidence_spelling_is_normalised(given, stored):
    assert parse_project_items(reply(raw(confidence=given)))[0].confidence == stored


@pytest.mark.parametrize("bad", ["certain", "90%", "", None])
def test_other_confidence_values_are_rejected(bad):
    with pytest.raises(ExtractionError, match="Expected High, Medium or Low"):
        parse_project_items(reply(raw(confidence=bad)))


def test_confidence_levels_are_as_specified():
    assert CONFIDENCE_LEVELS == ("High", "Medium", "Low")


@pytest.mark.parametrize("placeholder", [None, "", "N/A", "Unassigned", "TBC", "unknown", "nobody", "not stated"])
def test_missing_owner_and_due_date_become_not_stated(placeholder):
    (item,) = parse_project_items(reply(raw(owner=placeholder, due_date=placeholder)))

    assert item.owner == NOT_STATED == "Not stated"
    assert item.due_date == NOT_STATED


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "empty response"),
        ("Here are the items.", "not valid JSON"),
        ('{"things": []}', 'no "items" list'),
        (json.dumps({"items": ["text"]}), "Item 1 is not a JSON object"),
        (reply(raw(description=" ")), "has no description"),
    ],
)
def test_bad_replies_raise_readable_errors(text, message):
    with pytest.raises(ExtractionError, match=message):
        parse_project_items(text)


def test_code_fence_is_stripped():
    assert len(parse_project_items(f"```json\n{reply(raw())}\n```")) == 1


def test_empty_items_list_is_valid():
    assert parse_project_items('{"items": []}') == []


# --- PM review flags (context-sensitive) ----------------------------------

def test_complete_action_needs_no_review():
    (item,) = extract(raw())

    assert not item.needs_pm_review
    assert item.review_reasons == ()


def test_tc02_action_without_owner_is_flagged():
    (item,) = extract(raw(owner=None, description="Update the RAID log.",
                          source={"speaker": "Kat", "quote": "We need to have the demo ready"}))

    assert item.owner == "Not stated"
    assert item.needs_pm_review
    assert "No owner stated." in item.review_reasons


@pytest.mark.parametrize("item_type", ["Decision", "Assumption", "Risk", "Issue", "Dependency"])
def test_other_types_may_legitimately_lack_owner_and_date(item_type):
    (item,) = extract(raw(type=item_type, owner=None, due_date=None))

    assert not item.needs_pm_review


def test_action_without_due_date_is_not_flagged_by_rule():
    (item,) = extract(raw(due_date=None))

    assert not item.needs_pm_review


def test_tc03_low_confidence_is_flagged():
    (item,) = extract(raw(owner=None, confidence="Low", description="Chloe might send the RAID document.",
                          source={"speaker": "Kat", "quote": "Maybe Chloe could send us the RAID document."}))

    assert item.owner == "Not stated"
    assert LOW_CONFIDENCE_REASON in item.review_reasons


def test_model_flag_and_reason_are_kept_with_rule_reasons():
    (item,) = extract(raw(owner=None, needs_pm_review=True, review_reason="Ownership was contested."))

    assert item.review_reasons == ("Ownership was contested.", "No owner stated.")


def test_model_flag_without_reason_gets_a_generic_one():
    (item,) = extract(raw(needs_pm_review=True, review_reason=None))

    assert item.review_reasons == ("Flagged for review by the model.",)


def test_reason_without_flag_is_ignored():
    (item,) = extract(raw(needs_pm_review=False, review_reason="Something"))

    assert not item.needs_pm_review


# --- evidence ---------------------------------------------------------------

def test_verified_evidence():
    (item,) = extract(raw())

    assert item.source.verified


def test_fabricated_quote_is_flagged():
    (item,) = extract(raw(source={"speaker": "Annie", "quote": "I will deliver it by 5pm Thursday."}))

    assert not item.source.verified
    assert "Source quote not found in the transcript." in item.review_reasons


def test_fabricated_timestamp_is_flagged():
    (item,) = extract(raw(source={"speaker": "Annie", "quote": "I'll investigate", "timestamp": "14:55"}))

    assert "Timestamp '14:55' not found in the transcript." in item.review_reasons


def test_fabricated_speaker_is_flagged():
    (item,) = extract(raw(source={"speaker": "Priya", "quote": "I'll investigate"}))

    assert "Speaker 'Priya' not found in the transcript." in item.review_reasons


def test_quote_matching_ignores_case_spacing_and_curly_quotes():
    evidence = check_evidence(Evidence(speaker="Izzy", quote="I'll ASK chloe for one."), TRANSCRIPT)

    assert evidence.verified


def test_evidence_accepts_a_bare_quote_string():
    assert parse_evidence("We need to have the demo ready") == Evidence(speaker=None, quote="We need to have the demo ready")


def test_null_timestamp_placeholders_become_none():
    assert parse_evidence({"speaker": "Kat", "quote": "x", "timestamp": "N/A"}).timestamp is None


# --- due dates -------------------------------------------------------------

def test_tc06_relative_due_date_resolved_with_meeting_date():
    (item,) = extract(raw(due_date="tomorrow"), meeting_date=date(2026, 9, 23))

    assert item.due_date == "tomorrow"
    assert item.due_date_resolved == "2026-09-24"
    assert not item.needs_pm_review


def test_tc06_relative_due_date_without_meeting_date_is_left_and_flagged():
    (item,) = extract(raw(due_date="tomorrow"))

    assert item.due_date == "tomorrow"
    assert item.due_date_resolved is None
    assert item.needs_pm_review


# --- duplicates ------------------------------------------------------------

def test_tc08_repeated_action_becomes_one_record():
    items = extract(
        raw(),
        raw(description="investigate automatic   transcript detection."),
        raw(description="Look into detecting transcripts.", source={"speaker": "Annie", "quote": "I'll investigate whether the system"}),
    )

    assert len(items) == 1


def test_separate_commitments_are_kept():
    items = extract(raw(), raw(description="Ask Chloe for a transcript.", owner="Izzy",
                               source={"speaker": "Izzy", "quote": "I'll ask Chloe for one."}))

    assert len(items) == 2


def test_same_description_different_type_is_not_a_duplicate():
    assert len(extract(raw(), raw(type="Dependency"))) == 2


# --- Markdown (presentation only) -----------------------------------------

def test_markdown_has_every_section_in_order():
    markdown = items_to_markdown([])
    headings = [line for line in markdown.splitlines() if line.startswith("## ")]

    assert headings == ["## Actions", "## Decisions", "## Risks", "## Issues",
                        "## Dependencies", "## Assumptions", "## Needs PM Review"]
    assert markdown.count("None identified.") == 7


def test_markdown_counts_and_review_list():
    items = extract(raw(), raw(owner=None, description="Update the RAID log.",
                               source={"speaker": "Kat", "quote": "We need to have the demo ready"}))

    markdown = items_to_markdown(items)

    assert "2 items: 2 Actions. 1 needs PM review." in markdown
    assert "- **Action 2: Update the RAID log.** No owner stated." in markdown


def test_markdown_shows_resolved_date_and_unverified_source():
    (item,) = extract(raw(due_date="tomorrow", source={"speaker": "Annie", "quote": "Invented words."}),
                      meeting_date=date(2026, 9, 23))

    markdown = items_to_markdown([item])

    assert "tomorrow (2026-09-24)" in markdown
    assert 'Annie: "Invented words." (NOT VERIFIED)' in markdown


def test_markdown_escapes_table_breaking_characters():
    (item,) = extract(raw(description="Use A | B\nnext line"))

    assert "Use A \\| B next line" in items_to_markdown([item])
