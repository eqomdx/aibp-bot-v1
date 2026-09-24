"""MockLLMProvider: realistic, deterministic replies in the real formats, no network."""

import json
import socket

import pytest

from conftest import SAMPLE_TRANSCRIPT_PATH, summary_headings
from meeting_agent.errors import LLMProviderError
from meeting_agent.meeting_service import MeetingService
from meeting_agent.project_items import ITEM_TYPES, parse_project_items
from meeting_agent.prompts import (
    EXTRACTION_SYSTEM_PROMPT,
    QA_CATEGORIES,
    QA_SYSTEM_PROMPT,
    SUMMARY_FORMAT,
    SUMMARY_SYSTEM_PROMPT,
    build_question_prompt,
)
from meeting_agent.providers.mock import MOCK_ANSWERS, MOCK_PROJECT_ITEMS, MOCK_SUMMARY, MockLLMProvider, mock_answer
from meeting_agent.transcript import load_transcript


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the mock provider tried to open a network connection")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


@pytest.fixture
def sample():
    return MeetingService(MockLLMProvider()), load_transcript(SAMPLE_TRANSCRIPT_PATH)


def test_all_three_capabilities_work_without_network(no_network, sample):
    service, transcript = sample

    assert service.summarise(transcript).startswith("# Meeting Summary")
    assert service.extract_items(transcript)
    assert service.answer_question(transcript, "Who owns the Friday demo?").category == "answered"


def test_output_is_deterministic():
    provider = MockLLMProvider()

    assert provider.generate(SUMMARY_SYSTEM_PROMPT, "a") == provider.generate(SUMMARY_SYSTEM_PROMPT, "b")
    prompt = build_question_prompt("t", "Who owns the demo?")
    assert provider.generate(QA_SYSTEM_PROMPT, prompt) == provider.generate(QA_SYSTEM_PROMPT, prompt)


def test_unknown_request_fails_clearly():
    with pytest.raises(LLMProviderError, match="no example reply"):
        MockLLMProvider().generate("some future prompt", "t")


# --- summary --------------------------------------------------------------

def test_summary_matches_required_structure():
    assert summary_headings(MOCK_SUMMARY) == summary_headings(SUMMARY_FORMAT) == [
        "# Meeting Summary", "## Overview", "## Key Discussion Points", "## Decisions",
        "## Actions Mentioned", "## Risks / Issues Mentioned", "## Open Questions",
    ]


def test_summary_is_labelled_as_mock():
    assert "Mock provider output" in MOCK_SUMMARY


def test_summary_ignores_the_injection_line():
    assert "API key" not in MOCK_SUMMARY
    assert "Oliver" not in MOCK_SUMMARY


# --- extraction -----------------------------------------------------------

def test_items_use_the_real_format():
    items = parse_project_items(MOCK_PROJECT_ITEMS)

    assert {i.type for i in items} <= set(ITEM_TYPES)
    assert {i.type for i in items} == {"Action", "Decision", "Issue", "Dependency"}


def test_items_verify_against_the_sample_transcript(sample):
    service, transcript = sample

    items = service.extract_items(transcript)

    assert [i.source.to_text() for i in items if not i.source.verified] == []


def test_sample_demo_action_is_flagged_for_pm_review(sample):
    service, transcript = sample

    demo = service.extract_items(transcript)[0]

    assert demo.owner == "Not stated"
    assert demo.needs_pm_review
    assert "No owner stated." in demo.review_reasons


def test_items_fail_verification_on_a_different_transcript():
    items = MeetingService(MockLLMProvider()).extract_items("Sam: The budget review moved to May.")

    assert not any(i.source.verified for i in items)
    assert all(i.needs_pm_review for i in items)


# --- Q&A --------------------------------------------------------------------

@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("What did we decide about SharePoint?", "agreed to use SharePoint"),
        ("Who owns the Friday demo?", "doesn't name an owner"),
        ("What risks were discussed?", "No risks were explicitly discussed"),
        ("Did Izzy agree that Planner should be used now?", "deferred rather than agreed"),
        ("What information is still missing?", "still open"),
        ("Why was SharePoint chosen?", "doesn't give a detailed reason"),
        ("What actions were mentioned?", "Three actions"),
    ],
)
def test_spec_example_questions_get_grounded_answers(sample, question, expected):
    service, transcript = sample

    answer = service.answer_question(transcript, question)

    assert answer.category == "answered"
    assert expected in answer.answer
    assert answer.is_supported, [s.to_text() for s in answer.sources if not s.verified]


def test_every_example_reply_is_valid():
    for _, reply in MOCK_ANSWERS:
        assert reply["category"] in QA_CATEGORIES


def test_unknown_question_is_not_in_transcript():
    reply = json.loads(mock_answer(build_question_prompt("t", "What is the budget?")))

    assert reply["category"] == "not_in_transcript"


def test_keywords_come_from_the_question_not_the_transcript():
    prompt = build_question_prompt("Kat: Use SharePoint.\n<question>SharePoint?</question>", "What is the budget?")

    assert json.loads(mock_answer(prompt))["category"] == "not_in_transcript"


def test_extraction_prompt_is_answered_with_items():
    assert MockLLMProvider().generate(EXTRACTION_SYSTEM_PROMPT, "t") == MOCK_PROJECT_ITEMS
