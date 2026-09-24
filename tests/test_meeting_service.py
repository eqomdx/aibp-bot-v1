"""MeetingService: prompts in, checked results out, for all three capabilities."""

from datetime import date

import pytest

from meeting_agent.errors import ExtractionError, QuestionError, SummarisationError
from meeting_agent.meeting_service import MeetingService
from meeting_agent.prompts import (
    EXTRACTION_FORMAT,
    EXTRACTION_INSTRUCTIONS,
    EXTRACTION_SYSTEM_PROMPT,
    QA_INSTRUCTIONS,
    QA_SYSTEM_PROMPT,
    SUMMARY_FORMAT,
    SUMMARY_SYSTEM_PROMPT,
)
from meeting_agent.qa import Turn

TRANSCRIPT = "Kat: We need to have the demo ready for Friday."


# --- Phase 1: summarise -------------------------------------------------------

def test_summary_sends_transcript_and_summary_prompts(fake_provider):
    provider = fake_provider()

    MeetingService(provider).summarise(TRANSCRIPT)

    (call,) = provider.calls
    assert call["system_prompt"] == SUMMARY_SYSTEM_PROMPT
    assert TRANSCRIPT in call["user_prompt"]
    assert SUMMARY_FORMAT in call["user_prompt"]
    assert "None identified." in call["user_prompt"]


def test_summary_prompt_forbids_invention_and_distinguishes_agreement():
    for word in ("people", "responsibilities", "dates", "deadlines", "decisions", "risks",
                 "issues", "project facts", "motives", "outcomes"):
        assert word in SUMMARY_SYSTEM_PROMPT
    assert "A suggestion" in SUMMARY_SYSTEM_PROMPT and "is not a decision" in SUMMARY_SYSTEM_PROMPT
    assert "Preserve uncertainty" in SUMMARY_SYSTEM_PROMPT


def test_summary_is_returned_trimmed(fake_provider):
    provider = fake_provider(reply="\n# Meeting Summary\n\n## Overview\nDemo planning.\n\n")

    assert MeetingService(provider).summarise(TRANSCRIPT) == "# Meeting Summary\n\n## Overview\nDemo planning."


@pytest.mark.parametrize("reply", ["", "  \n\t", None])
def test_empty_summary_is_rejected(fake_provider, reply):
    with pytest.raises(SummarisationError, match="empty summary"):
        MeetingService(fake_provider(reply=reply)).summarise(TRANSCRIPT)


# --- Phase 2: extract_items ---------------------------------------------------

ITEMS_REPLY = """{"items": [
  {"project": "AIBP", "meeting_date": "2026-09-23", "type": "Action", "title": "Prepare demo", "description": "Have the demo ready.", "owner": "Not stated", "due_date": "Friday",
   "source": {"speaker": "Kat", "quote": "We need to have the demo ready for Friday.", "timestamp": null},
   "confidence": "Medium", "needs_pm_review": false, "review_reason": null},
  {"project": "AIBP", "meeting_date": "2026-09-23", "type": "Action", "title": "Prepare demo", "description": "Have the demo ready.", "owner": "Not stated", "due_date": "Friday",
   "source": {"speaker": "Kat", "quote": "We need to have the demo ready for Friday.", "timestamp": null},
   "confidence": "Medium", "needs_pm_review": false, "review_reason": null},
  {"project": "AIBP", "meeting_date": "2026-09-23", "type": "Decision", "title": "Demo ownership", "description": "Kat owns the demo.", "owner": "Kat", "due_date": "Not stated",
   "source": {"speaker": "Kat", "quote": "Kat agreed to own the demo.", "timestamp": null},
   "confidence": "High", "needs_pm_review": false, "review_reason": null}
]}"""


def test_extraction_sends_transcript_and_extraction_prompts(fake_provider):
    provider = fake_provider(items_reply=ITEMS_REPLY)

    MeetingService(provider).extract_items(TRANSCRIPT)

    (call,) = provider.calls
    assert call["system_prompt"] == EXTRACTION_SYSTEM_PROMPT
    assert TRANSCRIPT in call["user_prompt"]
    assert EXTRACTION_FORMAT in call["user_prompt"]


def test_extraction_deduplicates_checks_and_flags(fake_provider):
    items = MeetingService(fake_provider(items_reply=ITEMS_REPLY)).extract_items(TRANSCRIPT, date(2026, 9, 23))

    action, decision = items
    assert action.owner == "Not stated"
    assert action.due_date_resolved == "2026-09-25"
    assert action.review_reasons == ("No owner stated.",)
    assert decision.source.verified is False
    assert "Source quote not found in the transcript." in decision.review_reasons


def test_extraction_prompt_covers_the_classification_rules():
    for phrase in ("Risk: something that might go wrong", "Issue: a problem that exists now",
                   "Assumption: something treated as true", "Tentative wording", "Corrections:",
                   "Duplicates:", "never invent timestamps", "(suggested)", "mitigation_next_step"):
        assert phrase in EXTRACTION_INSTRUCTIONS


def test_unparseable_extraction_reply_is_rejected(fake_provider):
    with pytest.raises(ExtractionError, match="not valid JSON"):
        MeetingService(fake_provider(items_reply="I could not find any items.")).extract_items(TRANSCRIPT)


# --- Phase 3: answer_question -------------------------------------------------

ANSWER_REPLY = """{"category": "answered", "answer": "The demo is due Friday; no owner was named.",
 "sources": [{"speaker": "Kat", "quote": "We need to have the demo ready for Friday.", "timestamp": null}]}"""


def test_question_is_sent_with_transcript_and_qa_prompt(fake_provider):
    provider = fake_provider(answer_reply=ANSWER_REPLY)

    MeetingService(provider).answer_question(TRANSCRIPT, "  Who owns the demo?  ")

    (call,) = provider.calls
    assert call["system_prompt"] == QA_SYSTEM_PROMPT
    assert TRANSCRIPT in call["user_prompt"]
    assert "<question>\nWho owns the demo?\n</question>" in call["user_prompt"]


def test_answer_is_returned_with_checked_sources(fake_provider):
    answer = MeetingService(fake_provider(answer_reply=ANSWER_REPLY)).answer_question(TRANSCRIPT, "Who owns the demo?")

    assert answer.question == "Who owns the demo?"
    assert answer.category == "answered"
    assert answer.is_supported


def test_history_is_passed_for_follow_ups(fake_provider):
    provider = fake_provider(answer_reply=ANSWER_REPLY)

    MeetingService(provider).answer_question(TRANSCRIPT, "Who owns it?", [Turn("When is the demo?", "Friday.")])

    assert "Q: When is the demo?\nA: Friday." in provider.calls[0]["user_prompt"]


@pytest.mark.parametrize("question", ["", "   ", None])
def test_empty_question_is_rejected_without_calling_provider(fake_provider, question):
    provider = fake_provider()

    with pytest.raises(QuestionError, match="question is empty"):
        MeetingService(provider).answer_question(TRANSCRIPT, question)

    assert provider.calls == []


def test_qa_prompt_requires_grounding():
    assert "Use only the supplied transcript" in QA_SYSTEM_PROMPT
    assert "not_in_transcript" in QA_INSTRUCTIONS
