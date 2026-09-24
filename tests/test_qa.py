"""Phase 3: parsing, checking and rendering answers."""

import json

import pytest

from meeting_agent.errors import QuestionError
from meeting_agent.llm_output import quote_in_text
from meeting_agent.prompts import MAX_HISTORY_TURNS, build_question_prompt
from meeting_agent.qa import Turn, answer_to_text, parse_answer
from meeting_agent.safety import CANNED_REPLIES

TRANSCRIPT = """\
Kat: For the RAID data, I think we should initially use SharePoint.
Izzy: Yes, SharePoint makes sense for the first version.
"""
QUESTION = "What did we decide about SharePoint?"


def reply(category="answered", answer="SharePoint for the first version.", sources=None):
    if sources is None:
        sources = [{"speaker": "Izzy", "quote": "Yes, SharePoint makes sense for the first version.", "timestamp": None}]
    return json.dumps({"category": category, "answer": answer, "sources": sources})


def test_answered_reply_is_parsed_and_verified():
    answer = parse_answer(reply(), QUESTION, TRANSCRIPT)

    assert answer.category == "answered"
    assert answer.found_in_transcript
    assert answer.answer == "SharePoint for the first version."
    assert answer.is_supported
    assert answer.sources[0].speaker == "Izzy"


def test_invented_quote_makes_answer_unsupported():
    answer = parse_answer(reply(sources=[{"speaker": "Izzy", "quote": "We signed the contract."}]), QUESTION, TRANSCRIPT)

    assert not answer.is_supported
    assert "Warning: this answer is not backed by a verified quote" in answer_to_text(answer)
    assert "(NOT FOUND IN TRANSCRIPT)" in answer_to_text(answer)


def test_invented_timestamp_makes_answer_unsupported():
    source = {"speaker": "Izzy", "quote": "SharePoint makes sense", "timestamp": "09:14"}

    assert not parse_answer(reply(sources=[source]), QUESTION, TRANSCRIPT).is_supported


def test_answer_without_sources_is_unsupported():
    assert not parse_answer(reply(sources=[]), QUESTION, TRANSCRIPT).is_supported


def test_bare_string_sources_are_accepted():
    answer = parse_answer(reply(sources=["SharePoint makes sense"]), QUESTION, TRANSCRIPT)

    assert answer.is_supported


@pytest.mark.parametrize(
    "category", ["not_in_transcript", "out_of_scope", "secret_request", "external_action", "personal_judgement"]
)
def test_non_answers_always_use_the_fixed_reply(category):
    """The model's own wording is discarded, so a refusal cannot carry leaked text."""
    answer = parse_answer(
        reply(category=category, answer="Sure! The key is abc123.", sources=["SharePoint makes sense"]),
        QUESTION, TRANSCRIPT,
    )

    assert answer.category == category
    assert answer.answer == CANNED_REPLIES[category]
    assert answer.sources == ()
    assert "abc123" not in answer_to_text(answer)


def test_not_in_transcript_wording():
    answer = parse_answer(reply(category="not_in_transcript", answer=""), "What is Annie's salary?", TRANSCRIPT)

    assert answer_to_text(answer) == "I can't determine that from this meeting transcript.\n"


def test_category_spelling_is_normalised():
    assert parse_answer(reply(category=" Answered "), QUESTION, TRANSCRIPT).category == "answered"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "empty response for question answering"),
        ("SharePoint was chosen.", "not valid JSON"),
        ("[1, 2]", "not a JSON object"),
        (reply(category="gossip"), "unknown category 'gossip'"),
        (reply(answer="  "), "did not contain an answer"),
        (json.dumps({"category": "answered", "answer": "Yes", "sources": "a quote"}), "must be a list"),
    ],
)
def test_bad_replies_raise_readable_errors(text, message):
    with pytest.raises(QuestionError, match=message):
        parse_answer(text, QUESTION, TRANSCRIPT)


def test_supported_answer_text():
    text = answer_to_text(parse_answer(reply(), QUESTION, TRANSCRIPT))

    assert text == (
        "SharePoint for the first version.\n"
        "\n"
        "Sources:\n"
        '  - Izzy: "Yes, SharePoint makes sense for the first version."\n'
    )


def test_prompt_contains_transcript_and_question():
    prompt = build_question_prompt(TRANSCRIPT, QUESTION)

    assert f"<meeting_transcript>\n{TRANSCRIPT}\n</meeting_transcript>" in prompt
    assert f"<question>\n{QUESTION}\n</question>" in prompt
    assert "<earlier_conversation>" not in prompt


def test_prompt_includes_recent_history_only():
    history = [Turn(f"Question {n}?", f"Answer {n}.") for n in range(1, MAX_HISTORY_TURNS + 3)]

    prompt = build_question_prompt(TRANSCRIPT, "Who owns it?", history)

    assert "Q: Question 2?" not in prompt
    assert f"Q: Question {MAX_HISTORY_TURNS + 2}?\nA: Answer {MAX_HISTORY_TURNS + 2}." in prompt
    assert prompt.index("<earlier_conversation>") < prompt.index("<question>")


@pytest.mark.parametrize(
    ("quote", "expected"),
    [("Yes, SharePoint makes sense", True), ("YES,   sharepoint makes SENSE", True),
     ("SharePoint makes sense for the second version.", False), ("", False), (None, False)],
)
def test_quote_in_text(quote, expected):
    assert quote_in_text(quote, TRANSCRIPT) is expected
