import json

import pytest

from conftest import SAMPLE_TRANSCRIPT_PATH, summary_headings
from meeting_agent.errors import LLMProviderError
from meeting_agent.meeting_service import MeetingService
from meeting_agent.project_items import parse_project_items
from meeting_agent.prompts import (
    EXTRACTION_SYSTEM_PROMPT,
    QA_SYSTEM_PROMPT,
    SUMMARY_FORMAT,
    SUMMARY_SYSTEM_PROMPT,
    build_question_prompt,
)
from meeting_agent.providers.mock import MOCK_PROJECT_ITEMS, MOCK_SUMMARY, MockLLMProvider, mock_answer
from meeting_agent.transcript import load_transcript


def test_output_is_deterministic():
    provider = MockLLMProvider()

    first = provider.generate(SUMMARY_SYSTEM_PROMPT, "transcript A")
    second = provider.generate(SUMMARY_SYSTEM_PROMPT, "transcript B")

    assert first == second == MOCK_SUMMARY


def test_reply_depends_on_the_request_type():
    provider = MockLLMProvider()

    assert provider.generate(SUMMARY_SYSTEM_PROMPT, "t") == MOCK_SUMMARY
    assert provider.generate(EXTRACTION_SYSTEM_PROMPT, "t") == MOCK_PROJECT_ITEMS


def test_unknown_request_fails_clearly():
    with pytest.raises(LLMProviderError, match="no example reply"):
        MockLLMProvider().generate("some future prompt", "t")


def test_summary_matches_required_structure():
    headings = summary_headings(MOCK_SUMMARY)

    assert headings == summary_headings(SUMMARY_FORMAT)
    assert headings == [
        "# Meeting Summary",
        "## Overview",
        "## Key Discussion Points",
        "## Decisions",
        "## Actions Mentioned",
        "## Risks / Issues Mentioned",
        "## Open Questions",
    ]


def test_summary_is_labelled_as_mock():
    assert "Mock provider output" in MOCK_SUMMARY


def test_every_summary_section_has_content():
    for section in MOCK_SUMMARY.split("\n## ")[1:]:
        heading, _, body = section.partition("\n")
        assert body.strip(), f"section '{heading}' is empty"


def test_mock_items_are_valid():
    items = parse_project_items(MOCK_PROJECT_ITEMS)

    assert {i.type for i in items} == {"action", "decision", "issue", "dependency"}


def test_mock_items_all_verify_against_sample_transcript():
    transcript = load_transcript(SAMPLE_TRANSCRIPT_PATH)

    items = MeetingService(MockLLMProvider()).extract_items(transcript)

    unverified = [i.source for i in items if not i.source_verified]
    assert unverified == []


def test_mock_items_flag_sources_for_a_different_transcript():
    items = MeetingService(MockLLMProvider()).extract_items("Sam: The budget review moved to May.")

    assert not any(i.source_verified for i in items)


def test_summary_works_through_meeting_service():
    summary = MeetingService(MockLLMProvider()).summarise("Kat: Demo on Friday.")

    assert summary == MOCK_SUMMARY.strip()


# --- Phase 3: example answers --------------------------------------------

@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("What did we decide about SharePoint?", "agreed to use SharePoint"),
        ("Who owns the Friday demo?", "does not name an owner"),
        ("What unresolved risks were discussed?", "No risks were explicitly discussed"),
    ],
)
def test_example_answers_are_grounded_in_sample_transcript(question, expected):
    transcript = load_transcript(SAMPLE_TRANSCRIPT_PATH)

    answer = MeetingService(MockLLMProvider()).answer_question(transcript, question)

    assert expected in answer.answer
    assert answer.answer.startswith("[Mock]")
    assert answer.found_in_transcript
    assert answer.is_supported, [s.quote for s in answer.sources if not s.verified]


def test_unknown_question_gets_not_found_answer():
    answer = MeetingService(MockLLMProvider()).answer_question("Kat: Hi.", "What is the budget?")

    assert not answer.found_in_transcript
    assert answer.sources == []
    assert "only has example answers" in answer.answer


def test_answers_are_deterministic():
    provider = MockLLMProvider()
    prompt = build_question_prompt("t", "Who owns the demo?")

    assert provider.generate(QA_SYSTEM_PROMPT, prompt) == provider.generate(QA_SYSTEM_PROMPT, prompt)


def test_keyword_is_read_from_the_question_not_the_transcript():
    # The transcript mentions SharePoint, but the question does not.
    prompt = build_question_prompt("Kat: Use SharePoint.", "What is the budget?")

    assert json.loads(mock_answer(prompt))["found_in_transcript"] is False
