"""Scenario fixtures (TC01-TC13) and the evaluate runner."""

from pathlib import Path

import pytest

from meeting_agent import evaluate as ev
from meeting_agent.meeting_service import MeetingService
from meeting_agent.providers.mock import MockLLMProvider

SCENARIOS_PATH = Path(__file__).resolve().parents[1] / "scenarios" / "scenarios.json"


@pytest.fixture
def scenarios():
    return ev.load_scenarios(SCENARIOS_PATH)


def test_every_spec_test_case_has_a_scenario(scenarios):
    ids = {s["id"] for s in scenarios}

    for n in range(1, 14):
        assert any(i.startswith(f"TC{n:02d}") for i in ids), f"TC{n:02d} missing"


def test_scenarios_are_well_formed(scenarios):
    for scenario in scenarios:
        assert scenario["transcript"].strip()
        assert scenario["checks"]
        for check in scenario["checks"]:
            assert any(kind in check for kind in ev.CHECK_KINDS), f"{scenario['id']}: unknown check {check}"
            if any(kind in check for kind in ev.ANSWER_CHECKS):
                assert scenario.get("question"), f"{scenario['id']} needs a question"


def test_app_enforced_scenarios_pass_with_the_mock(scenarios):
    results = ev.evaluate(MeetingService(MockLLMProvider()), scenarios, real_model=False)

    ran = [r for r in results if r.status != "SKIP"]
    assert {r.scenario_id for r in ran} == {"TC10", "TC13"}
    assert all(r.status == "PASS" for r in ran), [(r.scenario_id, r.failures) for r in ran]


def test_model_scenarios_are_skipped_with_the_mock(scenarios):
    results = ev.evaluate(MeetingService(MockLLMProvider()), scenarios, real_model=False)

    assert sum(r.status == "SKIP" for r in results) == len(scenarios) - 2


def test_cli_with_mock(monkeypatch, capsys):
    monkeypatch.setattr(ev, "load_environment", lambda: None)
    monkeypatch.setenv("LLM_PROVIDER", "mock")

    assert ev.main([str(SCENARIOS_PATH)]) == 0
    assert "2 passed, 0 failed, 12 skipped." in capsys.readouterr().out


# --- the check engine -------------------------------------------------------

ITEMS = [
    {"type": "Action", "owner": "Annie", "confidence": "High", "description": "Send the use case.",
     "needs_pm_review": False, "due_date_resolved": None},
    {"type": "Action", "owner": "Not stated", "confidence": "Low", "description": "Update the RAID log.",
     "needs_pm_review": True, "due_date_resolved": "2026-09-24"},
]


@pytest.mark.parametrize(
    ("check", "passes"),
    [
        ({"item": {"type": "action", "owner": "annie"}}, True),
        ({"item": {"type": "Risk"}}, False),
        ({"item": {"description": {"contains": "raid"}}}, True),
        ({"item": {"needs_pm_review": True, "due_date_resolved": "2026-09-24"}}, True),
        ({"item": {"due_date_resolved": None, "owner": "Annie"}}, True),
        ({"no_item": {"owner": "Chloe"}}, True),
        ({"no_item": {"owner": "Annie"}}, False),
        ({"max_items": 2, "where": {"type": "Action"}}, True),
        ({"max_items": 1, "where": {"type": "Action"}}, False),
    ],
)
def test_item_checks(check, passes):
    assert (ev.evaluate_check(check, ITEMS, None, None) is None) is passes


def test_summary_and_answer_checks():
    from meeting_agent.qa import Answer

    answer = Answer(question="?", category="answered", answer="Annie will send it.")
    summary = "# Meeting Summary\n\n## Overview\nShort."

    assert ev.evaluate_check({"category": "answered"}, None, None, answer) is None
    assert ev.evaluate_check({"category": "secret_request"}, None, None, answer) is not None
    assert ev.evaluate_check({"answer_excludes": ["sk-"]}, None, None, answer) is None
    assert ev.evaluate_check({"answer_excludes": ["annie"]}, None, None, answer) is not None
    assert ev.evaluate_check({"summary_contains": ["## Overview"]}, None, summary, None) is None
    assert ev.evaluate_check({"summary_max_words": 3}, None, summary, None) is not None
