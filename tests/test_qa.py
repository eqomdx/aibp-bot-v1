import json

import pytest

from meeting_agent.errors import QuestionError
from meeting_agent.llm_output import quote_in_text
from meeting_agent.prompts import MAX_HISTORY_TURNS, build_question_prompt
from meeting_agent.qa import Answer, Source, Turn, answer_to_text, parse_answer

TRANSCRIPT = """\
Kat: For the RAID data, I think we should initially use SharePoint.
Izzy: Yes, SharePoint makes sense for the first version.
"""
QUESTION = "What did we decide about SharePoint?"


def reply(answer="SharePoint for the first version.", found=True, sources=None):
    if sources is None:
        sources = ["Yes, SharePoint makes sense for the first version."]
    return json.dumps({"answer": answer, "found_in_transcript": found, "sources": sources})


# --- parsing -------------------------------------------------------------

def test_valid_reply_parses_and_verifies():
    answer = parse_answer(reply(), QUESTION, TRANSCRIPT)

    assert answer == Answer(
        question=QUESTION,
        answer="SharePoint for the first version.",
        found_in_transcript=True,
        sources=[Source("Yes, SharePoint makes sense for the first version.", verified=True)],
    )
    assert answer.is_supported


def test_invented_quote_is_not_verified():
    answer = parse_answer(reply(sources=["We signed the SharePoint contract."]), QUESTION, TRANSCRIPT)

    assert answer.sources == [Source("We signed the SharePoint contract.", verified=False)]
    assert not answer.is_supported


def test_one_bad_quote_makes_answer_unsupported():
    sources = ["Yes, SharePoint makes sense for the first version.", "Planner is cancelled."]

    answer = parse_answer(reply(sources=sources), QUESTION, TRANSCRIPT)

    assert [s.verified for s in answer.sources] == [True, False]
    assert not answer.is_supported


def test_found_answer_without_sources_is_unsupported():
    assert not parse_answer(reply(sources=[]), QUESTION, TRANSCRIPT).is_supported


def test_blank_sources_are_dropped():
    answer = parse_answer(reply(sources=["", "  ", None]), QUESTION, TRANSCRIPT)

    assert answer.sources == []


def test_code_fence_is_stripped():
    answer = parse_answer(f"```json\n{reply()}\n```", QUESTION, TRANSCRIPT)

    assert answer.found_in_transcript


def test_not_found_answer_parses():
    answer = parse_answer(
        reply(answer="The transcript does not say.", found=False, sources=[]), "Budget?", TRANSCRIPT
    )

    assert not answer.found_in_transcript
    assert answer.sources == []


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "empty response for question answering"),
        ("SharePoint was chosen.", "not valid JSON"),
        ("[1, 2]", "not a JSON object"),
        (reply(answer="  "), "did not contain an answer"),
        (json.dumps({"answer": "Yes", "sources": []}), "found_in_transcript"),
        (json.dumps({"answer": "Yes", "found_in_transcript": "yes", "sources": []}), "found_in_transcript"),
        (json.dumps({"answer": "Yes", "found_in_transcript": True, "sources": "a quote"}), "must be a list"),
    ],
    ids=["empty", "prose", "not-object", "blank-answer", "no-found-flag", "found-not-bool", "sources-not-list"],
)
def test_bad_replies_raise_readable_errors(text, message):
    with pytest.raises(QuestionError, match=message):
        parse_answer(text, QUESTION, TRANSCRIPT)


# --- rendering -----------------------------------------------------------

def test_supported_answer_text():
    text = answer_to_text(parse_answer(reply(), QUESTION, TRANSCRIPT))

    assert text == (
        "SharePoint for the first version.\n"
        "\n"
        "Sources:\n"
        '  - "Yes, SharePoint makes sense for the first version."\n'
    )


def test_unsupported_answer_text_warns():
    text = answer_to_text(parse_answer(reply(sources=["Invented words."]), QUESTION, TRANSCRIPT))

    assert '"Invented words."  (NOT FOUND IN TRANSCRIPT)' in text
    assert "Warning: this answer is not backed by a verified quote" in text


def test_not_found_answer_text_has_no_sources_or_warning():
    answer = parse_answer(reply(answer="The transcript does not say.", found=False, sources=[]), "?", TRANSCRIPT)

    assert answer_to_text(answer) == "The transcript does not say.\n"


# --- prompt --------------------------------------------------------------

def test_prompt_contains_transcript_and_question():
    prompt = build_question_prompt(TRANSCRIPT, QUESTION)

    assert f"<transcript>\n{TRANSCRIPT}\n</transcript>" in prompt
    assert f"<question>\n{QUESTION}\n</question>" in prompt
    assert "<earlier_conversation>" not in prompt


def test_prompt_includes_recent_history_only():
    history = [Turn(f"Question {n}?", f"Answer {n}.") for n in range(1, MAX_HISTORY_TURNS + 3)]

    prompt = build_question_prompt(TRANSCRIPT, "Who owns it?", history)

    assert "Q: Question 1?" not in prompt
    assert "Q: Question 2?" not in prompt
    assert f"Q: Question {MAX_HISTORY_TURNS + 2}?\nA: Answer {MAX_HISTORY_TURNS + 2}." in prompt
    assert prompt.index("<earlier_conversation>") < prompt.index("<question>")


# --- shared quote matching ------------------------------------------------

@pytest.mark.parametrize(
    ("quote", "expected"),
    [
        ("Yes, SharePoint makes sense", True),
        ("YES,   sharepoint makes SENSE", True),
        ("Yes, SharePoint makes sense for the second version.", False),
        ("", False),
        (None, False),
    ],
)
def test_quote_in_text(quote, expected):
    assert quote_in_text(quote, TRANSCRIPT) is expected
