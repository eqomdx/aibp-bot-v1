import json

import pytest

from meeting_agent.errors import ExtractionError
from meeting_agent.project_items import (
    ITEM_TYPES,
    ProjectItem,
    items_to_markdown,
    parse_project_items,
    verify_sources,
)

TRANSCRIPT = """\
Kat: We need to have the demo ready for Friday.
Annie: I'll investigate   whether the system can detect a transcript automatically.
Izzy: I’ll ask Chloe for one.
"""


def item(**overrides):
    base = {
        "type": "action",
        "description": "Have the demo ready.",
        "owner": None,
        "due_date": "Friday",
        "source": "We need to have the demo ready for Friday.",
        "confidence": "medium",
    }
    return {**base, **overrides}


def reply(*items):
    return json.dumps({"items": list(items)})


# --- parsing -------------------------------------------------------------

def test_valid_reply_parses_into_items():
    (parsed,) = parse_project_items(reply(item()))

    assert parsed == ProjectItem(
        type="action",
        description="Have the demo ready.",
        owner=None,
        due_date="Friday",
        source="We need to have the demo ready for Friday.",
        confidence="medium",
        source_verified=False,
    )


def test_item_has_the_planned_fields():
    (parsed,) = parse_project_items(reply(item()))

    assert list(parsed.to_dict()) == [
        "type", "description", "owner", "due_date", "source", "confidence", "source_verified",
    ]


def test_empty_items_list_is_valid():
    assert parse_project_items('{"items": []}') == []


def test_bare_list_is_accepted():
    assert len(parse_project_items(json.dumps([item()]))) == 1


@pytest.mark.parametrize("fence", ["```json\n{}\n```", "```\n{}\n```", "```JSON\n{}\n```"])
def test_code_fence_is_stripped(fence):
    text = fence.replace("{}", reply(item()))

    assert len(parse_project_items(text)) == 1


def test_type_and_confidence_are_normalised():
    (parsed,) = parse_project_items(reply(item(type=" Decision ", confidence="HIGH")))

    assert (parsed.type, parsed.confidence) == ("decision", "high")


@pytest.mark.parametrize("placeholder", [None, "", "  ", "N/A", "Unassigned", "TBC", "unknown", "null"])
def test_not_stated_placeholders_become_none(placeholder):
    (parsed,) = parse_project_items(reply(item(owner=placeholder, due_date=placeholder)))

    assert parsed.owner is None
    assert parsed.due_date is None


def test_every_item_type_is_accepted():
    parsed = parse_project_items(reply(*(item(type=t) for t in ITEM_TYPES)))

    assert [p.type for p in parsed] == list(ITEM_TYPES)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "empty response"),
        ("   ", "empty response"),
        ("Here are the items: none", "not valid JSON"),
        ('{"things": []}', 'no "items" list'),
        ('"just a string"', 'no "items" list'),
        (json.dumps({"items": ["text"]}), "Item 1 is not a JSON object"),
        (reply(item(), item(type="milestone")), "Item 2 has unknown type 'milestone'"),
        (reply(item(description="  ")), "has no description"),
        (reply(item(confidence="certain")), "confidence 'certain'"),
    ],
    ids=["empty", "blank", "prose", "wrong-key", "not-object", "item-not-object",
         "bad-type", "no-description", "bad-confidence"],
)
def test_bad_replies_raise_readable_errors(text, message):
    with pytest.raises(ExtractionError, match=message):
        parse_project_items(text)


# --- source verification -------------------------------------------------

def _verified(source):
    (checked,) = verify_sources(parse_project_items(reply(item(source=source))), TRANSCRIPT)
    return checked.source_verified


def test_exact_quote_is_verified():
    assert _verified("We need to have the demo ready for Friday.")


def test_quote_with_speaker_name_is_verified():
    assert _verified("Kat: We need to have the demo ready for Friday.")


def test_matching_ignores_case_whitespace_and_curly_quotes():
    assert _verified("i'll INVESTIGATE whether the system")
    assert _verified("I'll ask Chloe for one.")  # transcript uses a curly apostrophe


def test_invented_quote_is_not_verified():
    assert not _verified("Kat will own the demo and deliver it by 5pm Thursday.")


def test_empty_source_is_not_verified():
    assert not _verified("")


# --- Markdown rendering --------------------------------------------------

def test_markdown_has_every_section_in_order():
    markdown = items_to_markdown([])
    headings = [line for line in markdown.splitlines() if line.startswith("## ")]

    assert headings == [f"## {h}" for h in ITEM_TYPES.values()]
    assert markdown.count("None identified.") == len(ITEM_TYPES)


def test_markdown_shows_item_fields_and_not_stated():
    items = verify_sources(parse_project_items(reply(item())), TRANSCRIPT)

    markdown = items_to_markdown(items)

    assert '| Have the demo ready. | Not stated | Friday | medium | "We need to have the demo ready for Friday." |' in markdown
    assert "NOT FOUND" not in markdown


def test_markdown_flags_unverified_sources():
    items = verify_sources(parse_project_items(reply(item(source="Something nobody said."))), TRANSCRIPT)

    markdown = items_to_markdown(items)

    assert "1 item(s) cite a source that was not found in the transcript" in markdown
    assert '"Something nobody said." (NOT FOUND IN TRANSCRIPT)' in markdown


def test_markdown_escapes_table_breaking_characters():
    items = parse_project_items(reply(item(description="Use A | B\nnext line")))

    assert "Use A \\| B next line" in items_to_markdown(items)
