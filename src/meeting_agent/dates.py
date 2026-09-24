"""Resolving due dates stated relative to the meeting ("tomorrow", "Friday").

Done in code rather than by the model, and only when it is safe: a relative
date is resolved only if the meeting date is known and the wording has one
reasonable reading. Anything else is left as stated and reported as a problem.
"""

import re
from datetime import date, timedelta

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

_ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_VAGUE = re.compile(r"\b(next week|this week|end of (?:the )?(?:week|month)|soon|asap)\b", re.IGNORECASE)
_NEXT_WEEKDAY = re.compile(r"\bnext\s+(" + "|".join(WEEKDAYS) + r")\b", re.IGNORECASE)
_WEEKDAY = re.compile(r"\b(" + "|".join(WEEKDAYS) + r")\b", re.IGNORECASE)


def resolve_due_date(text: str, meeting_date: date | None) -> tuple[date | None, str | None]:
    """Return (resolved date or None, problem or None) for a due date as stated."""
    iso = _ISO_DATE.search(text)
    if iso:
        try:
            return date.fromisoformat(iso.group(1)), None
        except ValueError:
            return None, f"Due date '{text}' is not a valid date."

    lowered = text.lower()
    is_today = re.search(r"\btoday\b", lowered)
    is_tomorrow = re.search(r"\btomorrow\b", lowered)
    next_weekday = _NEXT_WEEKDAY.search(text)
    weekday = _WEEKDAY.search(text)
    vague = _VAGUE.search(text)

    if not (is_today or is_tomorrow or next_weekday or weekday or vague):
        return None, None  # an absolute date in words, or nothing date-like: leave as stated

    if vague:
        return None, f"Due date '{text}' is not a specific date."
    if meeting_date is None:
        return None, f"Due date '{text}' is relative, and the meeting date is unknown."
    if is_today:
        return meeting_date, None
    if is_tomorrow:
        return meeting_date + timedelta(days=1), None
    if next_weekday:
        return None, f"Due date '{text}' could mean this week or the following week."

    target = WEEKDAYS.index(weekday.group(1).lower())
    days_ahead = (target - meeting_date.weekday()) % 7
    if days_ahead == 0:
        return None, f"Due date '{text}' was said on a {WEEKDAYS[target].title()}: today or next week?"
    return meeting_date + timedelta(days=days_ahead), None
