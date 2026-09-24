import pytest

from meeting_agent.errors import ExtractionError, QuestionError, SummarisationError
from meeting_agent.meeting_service import MeetingService
from meeting_agent.prompts import (
    EXTRACTION_FORMAT,
    EXTRACTION_SYSTEM_PROMPT,
    QA_SYSTEM_PROMPT,
    SUMMARY_FORMAT,
    SUMMARY_SYSTEM_PROMPT,
)
from meeting_agent.qa import Turn

TRANSCRIPT = "Kat: We need to have the demo ready for Friday."


def test_transcript_is_sent_to_provider(fake_provider):
    provider = fake_provider()

    MeetingService(provider).summarise(TRANSCRIPT)

    (call,) = provider.calls
    assert TRANSCRIPT in call["user_prompt"]


def test_correct_prompts_are_supplied(fake_provider):
    provider = fake_provider()

    MeetingService(provider).summarise(TRANSCRIPT)

    call = provider.calls[0]
    assert call["system_prompt"] == SUMMARY_SYSTEM_PROMPT
    assert SUMMARY_FORMAT in call["user_prompt"]
    assert "None identified." in call["user_prompt"]


def test_system_prompt_forbids_invention():
    for word in ("people", "responsibilities", "deadlines", "decisions", "risks", "issues"):
        assert f"- {word}" in SUMMARY_SYSTEM_PROMPT
    assert "actually agreed" in SUMMARY_SYSTEM_PROMPT
    assert "ambiguity" in SUMMARY_SYSTEM_PROMPT


def test_generated_response_is_returned(fake_provider):
    provider = fake_provider(reply="\n# Meeting Summary\n\n## Overview\nDemo planning.\n\n")

    summary = MeetingService(provider).summarise(TRANSCRIPT)

    assert summary == "# Meeting Summary\n\n## Overview\nDemo planning."


@pytest.mark.parametrize("reply", ["", "  \n\t", None], ids=["empty", "whitespace", "none"])
def test_empty_provider_response_fails(fake_provider, reply):
    service = MeetingService(fake_provider(reply=reply))

    with pytest.raises(SummarisationError, match="empty summary"):
        service.summarise(TRANSCRIPT)


# --- Phase 2: extract_items ----------------------------------------------

ITEMS_REPLY = """{"items": [
  {"type": "action", "description": "Have the demo ready.", "owner": null,
   "due_date": "Friday", "source": "We need to have the demo ready for Friday.",
   "confidence": "medium"},
  {"type": "decision", "description": "Kat owns the demo.", "owner": "Kat",
   "due_date": null, "source": "Kat agreed to own the demo.", "confidence": "high"}
]}"""


def test_extract_items_sends_transcript_with_extraction_prompts(fake_provider):
    provider = fake_provider(items_reply=ITEMS_REPLY)

    MeetingService(provider).extract_items(TRANSCRIPT)

    (call,) = provider.calls
    assert call["system_prompt"] == EXTRACTION_SYSTEM_PROMPT
    assert TRANSCRIPT in call["user_prompt"]
    assert EXTRACTION_FORMAT in call["user_prompt"]


def test_extract_items_returns_parsed_items(fake_provider):
    items = MeetingService(fake_provider(items_reply=ITEMS_REPLY)).extract_items(TRANSCRIPT)

    assert [(i.type, i.owner, i.due_date) for i in items] == [
        ("action", None, "Friday"),
        ("decision", "Kat", None),
    ]


def test_extract_items_flags_sources_missing_from_transcript(fake_provider):
    items = MeetingService(fake_provider(items_reply=ITEMS_REPLY)).extract_items(TRANSCRIPT)

    assert [i.source_verified for i in items] == [True, False]


def test_extract_items_rejects_unparseable_reply(fake_provider):
    service = MeetingService(fake_provider(items_reply="I could not find any items."))

    with pytest.raises(ExtractionError, match="not valid JSON"):
        service.extract_items(TRANSCRIPT)


def test_extraction_prompt_forbids_invention():
    for word in ("owners", "deadlines", "decisions", "dependencies", "assumptions"):
        assert f"- {word}" in EXTRACTION_SYSTEM_PROMPT
    assert "actually agreed" in EXTRACTION_SYSTEM_PROMPT


# --- Phase 3: answer_question --------------------------------------------

ANSWER_REPLY = """{"answer": "The demo is due Friday; no owner was named.",
 "found_in_transcript": true,
 "sources": ["We need to have the demo ready for Friday."]}"""


def test_answer_question_sends_transcript_question_and_qa_prompt(fake_provider):
    provider = fake_provider(answer_reply=ANSWER_REPLY)

    MeetingService(provider).answer_question(TRANSCRIPT, "  Who owns the demo?  ")

    (call,) = provider.calls
    assert call["system_prompt"] == QA_SYSTEM_PROMPT
    assert TRANSCRIPT in call["user_prompt"]
    assert "<question>\nWho owns the demo?\n</question>" in call["user_prompt"]


def test_answer_question_returns_verified_answer(fake_provider):
    answer = MeetingService(fake_provider(answer_reply=ANSWER_REPLY)).answer_question(
        TRANSCRIPT, "Who owns the demo?"
    )

    assert answer.question == "Who owns the demo?"
    assert answer.found_in_transcript
    assert answer.is_supported


def test_answer_question_passes_history(fake_provider):
    provider = fake_provider(answer_reply=ANSWER_REPLY)
    history = [Turn("When is the demo?", "Friday.")]

    MeetingService(provider).answer_question(TRANSCRIPT, "Who owns it?", history)

    assert "Q: When is the demo?\nA: Friday." in provider.calls[0]["user_prompt"]


@pytest.mark.parametrize("question", ["", "   ", None])
def test_empty_question_is_rejected_without_calling_provider(fake_provider, question):
    provider = fake_provider()

    with pytest.raises(QuestionError, match="question is empty"):
        MeetingService(provider).answer_question(TRANSCRIPT, question)

    assert provider.calls == []


def test_qa_prompt_forbids_invention_and_guessing():
    for word in ("owners", "deadlines", "decisions"):
        assert f"- {word}" in QA_SYSTEM_PROMPT
    assert "say so plainly" in QA_SYSTEM_PROMPT
    assert "actually agreed" in QA_SYSTEM_PROMPT
