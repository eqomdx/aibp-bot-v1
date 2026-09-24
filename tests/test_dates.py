"""TC06: relative due dates are resolved only when it is safe."""

from datetime import date

import pytest

from meeting_agent.dates import resolve_due_date

WEDNESDAY = date(2026, 9, 23)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("today", date(2026, 9, 23)),
        ("by end of today", date(2026, 9, 23)),
        ("tomorrow", date(2026, 9, 24)),
        ("Tomorrow morning", date(2026, 9, 24)),
        ("Friday", date(2026, 9, 25)),
        ("by Friday", date(2026, 9, 25)),
        ("Monday", date(2026, 9, 28)),
        ("2026-10-02", date(2026, 10, 2)),
    ],
)
def test_resolvable_dates(text, expected):
    assert resolve_due_date(text, WEDNESDAY) == (expected, None)


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("next Friday", "this week or the following week"),
        ("Wednesday", "said on a Wednesday"),
        ("next week", "not a specific date"),
        ("end of the month", "not a specific date"),
        ("soon", "not a specific date"),
    ],
)
def test_ambiguous_dates_are_not_resolved(text, problem):
    resolved, message = resolve_due_date(text, WEDNESDAY)

    assert resolved is None
    assert problem in message


@pytest.mark.parametrize("text", ["tomorrow", "Friday", "today"])
def test_relative_dates_need_the_meeting_date(text):
    resolved, message = resolve_due_date(text, None)

    assert resolved is None
    assert "meeting date is unknown" in message


@pytest.mark.parametrize("text", ["25 September", "Q3", "after the steering group"])
def test_non_relative_text_is_left_alone_without_a_problem(text):
    assert resolve_due_date(text, WEDNESDAY) == (None, None)


def test_iso_date_needs_no_meeting_date():
    assert resolve_due_date("2026-10-02", None) == (date(2026, 10, 2), None)


def test_invalid_iso_date_is_reported():
    resolved, message = resolve_due_date("2026-13-45", WEDNESDAY)

    assert resolved is None
    assert "not a valid date" in message
