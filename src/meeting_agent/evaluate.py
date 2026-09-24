"""Scenario checks for model behaviour (TC01-TC13 in scenarios/scenarios.json).

    python -m meeting_agent.evaluate [scenarios.json]

Each scenario runs through MeetingService with the configured provider and its
results are checked against simple expectations. Most scenarios test the
model's judgement (classification, ambiguity, corrections), so they only mean
something with a real model (LLM_PROVIDER=azure). With the mock provider only
the scenarios the application enforces in code are run; the rest are skipped.

Check kinds:
    {"item": {field: value, ...}}         at least one item matches
    {"no_item": {field: value, ...}}      no item matches
    {"max_items": n, "where": {...}}      at most n items match
    {"category": "secret_request"}        the answer's category
    {"answer_excludes": ["text", ...]}    none of the texts appear in the answer
    {"summary_contains": ["text", ...]}   all texts appear in the summary
    {"summary_max_words": n}              the summary is at most n words
A match value is compared case-insensitively; {"contains": "text"} matches a substring.
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from meeting_agent.app import build_service, use_utf8_console
from meeting_agent.config import get_provider_name, load_environment
from meeting_agent.errors import MeetingAgentError
from meeting_agent.meeting_service import MeetingService
from meeting_agent.transcript import detect_meeting_date

DEFAULT_SCENARIOS = Path("scenarios") / "scenarios.json"
ITEM_CHECKS = ("item", "no_item", "max_items")
SUMMARY_CHECKS = ("summary_contains", "summary_max_words")
ANSWER_CHECKS = ("category", "answer_excludes")
CHECK_KINDS = ITEM_CHECKS + SUMMARY_CHECKS + ANSWER_CHECKS


@dataclass
class Result:
    scenario_id: str
    title: str
    status: str  # PASS, FAIL or SKIP
    failures: list[str] = field(default_factory=list)


def load_scenarios(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_scenario(service: MeetingService, scenario: dict) -> list[str]:
    """Run one scenario and return its failed checks (empty if it passed)."""
    transcript = scenario["transcript"]
    checks = scenario["checks"]
    kinds = {kind for check in checks for kind in check if kind in CHECK_KINDS}

    items = summary = answer = None
    if kinds & set(ITEM_CHECKS):
        meeting_date = scenario.get("meeting_date")
        meeting_date = date.fromisoformat(meeting_date) if meeting_date else detect_meeting_date(transcript)
        items = [_flatten(item.to_dict()) for item in service.extract_items(transcript, meeting_date)]
    if kinds & set(SUMMARY_CHECKS):
        summary = service.summarise(transcript)
    if kinds & set(ANSWER_CHECKS):
        answer = service.answer_question(transcript, scenario["question"])

    return [failure for check in checks if (failure := evaluate_check(check, items, summary, answer))]


def evaluate_check(check: dict, items, summary, answer) -> str | None:
    """Return a description of the failure, or None if the check passed."""
    if "item" in check:
        return None if any(_matches(i, check["item"]) for i in items) else f"no item matching {check['item']}"
    if "no_item" in check:
        found = [i for i in items if _matches(i, check["no_item"])]
        return f"unexpected item {found[0]}" if found else None
    if "max_items" in check:
        count = sum(_matches(i, check.get("where", {})) for i in items)
        return None if count <= check["max_items"] else (
            f"{count} items matching {check.get('where', {})}, expected at most {check['max_items']}")
    if "category" in check:
        return None if answer.category == check["category"] else (
            f"answer category '{answer.category}', expected '{check['category']}'")
    if "answer_excludes" in check:
        leaked = [t for t in check["answer_excludes"] if t.lower() in answer.answer.lower()]
        return f"answer contains {leaked}" if leaked else None
    if "summary_contains" in check:
        missing = [t for t in check["summary_contains"] if t.lower() not in summary.lower()]
        return f"summary lacks {missing}" if missing else None
    if "summary_max_words" in check:
        words = len(summary.split())
        return None if words <= check["summary_max_words"] else (
            f"summary has {words} words, expected at most {check['summary_max_words']}")
    return f"unknown check {check}"


def evaluate(service: MeetingService, scenarios: list[dict], real_model: bool) -> list[Result]:
    results = []
    for scenario in scenarios:
        result = Result(scenario["id"], scenario["title"], "PASS")
        if not real_model and not scenario.get("app_enforced"):
            result.status = "SKIP"
        else:
            try:
                result.failures = run_scenario(service, scenario)
            except MeetingAgentError as exc:
                result.failures = [f"error: {exc}"]
            if result.failures:
                result.status = "FAIL"
        results.append(result)
    return results


def main(argv: list[str] | None = None) -> int:
    use_utf8_console()
    parser = argparse.ArgumentParser(prog="python -m meeting_agent.evaluate", description=__doc__.splitlines()[0])
    parser.add_argument("scenarios", nargs="?", default=str(DEFAULT_SCENARIOS))
    args = parser.parse_args(argv)
    load_environment()

    try:
        provider_name = get_provider_name()
        service = build_service(provider_name)
        scenarios = load_scenarios(Path(args.scenarios))
    except MeetingAgentError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error: could not read scenarios from {args.scenarios}: {exc}", file=sys.stderr)
        return 1

    real_model = provider_name != "mock"
    if not real_model:
        print("Mock provider: running only the scenarios the application enforces in code.\n"
              "Set LLM_PROVIDER=azure to test model behaviour.\n")

    results = evaluate(service, scenarios, real_model)
    for result in results:
        print(f"{result.status}  {result.scenario_id:<6} {result.title}")
        for failure in result.failures:
            print(f"        - {failure}")

    counts = {status: sum(r.status == status for r in results) for status in ("PASS", "FAIL", "SKIP")}
    print(f"\n{counts['PASS']} passed, {counts['FAIL']} failed, {counts['SKIP']} skipped.")
    return 1 if counts["FAIL"] else 0


def _flatten(item: dict) -> dict:
    """Lift source fields to the top level so checks can match them directly."""
    source = item.pop("source")
    return {**item, **{f"source_{key}": value for key, value in source.items()}}


def _matches(item: dict, expected: dict) -> bool:
    for key, want in expected.items():
        have = item.get(key)
        if isinstance(want, dict) and "contains" in want:
            if want["contains"].lower() not in str(have or "").lower():
                return False
        elif isinstance(want, str):
            if not isinstance(have, str) or have.lower() != want.lower():
                return False
        elif have != want:
            return False
    return True


if __name__ == "__main__":
    sys.exit(main())
