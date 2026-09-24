"""Mock provider for development and tests without live credentials.

Returns realistic, deterministic replies in the same formats the real model
must produce, and makes no network calls. The replies are written for the
sample transcript.md; they do not read whatever transcript is supplied. Run
against a different transcript, every quote fails verification, so mock
output cannot pass for a real analysis.
"""

import json
import re
from collections.abc import Callable

from meeting_agent.errors import LLMProviderError
from meeting_agent.prompts import EXTRACTION_SYSTEM_PROMPT, QA_SYSTEM_PROMPT, SUMMARY_SYSTEM_PROMPT

MOCK_SUMMARY = """\
# Meeting Summary

## Overview
_Mock provider output: fixed example text, not generated from the supplied transcript._ The team prepared for a Friday demo of the working end-to-end flow, agreed to use SharePoint for RAID data in the first version, and noted that a sample project transcript is still outstanding.

## Key Discussion Points
- The demo needs to be ready for Friday and should show the working end-to-end flow.
- Whether the system can detect a transcript automatically.
- SharePoint was proposed for RAID data initially; Planner may be revisited later.
- The team does not yet have a sample project transcript.

## Decisions
- SharePoint will be used for RAID data in the first version (proposed by Kat, agreed by Izzy).

## Actions Mentioned
- Annie: investigate whether the system can detect a transcript automatically and tell Kazim what she finds.
- Izzy: ask Chloe for a sample project transcript; if nothing suitable is available, create an example.
- Have the demo ready for Friday (no owner named).

## Risks / Issues Mentioned
- Issue: no sample project transcript is available yet.

## Open Questions
- Who owns preparing the Friday demo?
- Whether Planner will be used in a later version.
- Whether Chloe has a suitable sample transcript.
"""


def _source(speaker: str, quote: str) -> dict:
    return {"speaker": speaker, "quote": quote, "timestamp": None}


MOCK_PROJECT_ITEMS = json.dumps(
    {
        "items": [
            {
                "type": "Action",
                "description": "Have the demo ready, showing the working end-to-end flow.",
                "owner": "Not stated",
                "due_date": "Friday",
                "source": _source("Kat", "We need to have the demo ready for Friday."),
                "confidence": "Medium",
                "needs_pm_review": False,
                "review_reason": None,
            },
            {
                "type": "Action",
                "description": "Investigate whether the system can detect a transcript "
                "automatically and tell Kazim the findings.",
                "owner": "Annie",
                "due_date": "Not stated",
                "source": _source(
                    "Annie",
                    "I'll investigate whether the system can detect a transcript automatically "
                    "and let Kazim know what I find.",
                ),
                "confidence": "High",
                "needs_pm_review": False,
                "review_reason": None,
            },
            {
                "type": "Action",
                "description": "Ask Chloe for a sample project transcript; if she has nothing "
                "suitable, create an example.",
                "owner": "Izzy",
                "due_date": "Not stated",
                "source": _source("Izzy", "I'll ask Chloe for one. If she doesn't have anything suitable, "
                                          "I'll create an example."),
                "confidence": "High",
                "needs_pm_review": False,
                "review_reason": None,
            },
            {
                "type": "Decision",
                "description": "Use SharePoint for RAID data in the first version; Planner may be "
                "revisited later.",
                "owner": "Not stated",
                "due_date": "Not stated",
                "source": _source("Izzy", "Yes, SharePoint makes sense for the first version."),
                "confidence": "High",
                "needs_pm_review": False,
                "review_reason": None,
            },
            {
                "type": "Issue",
                "description": "The team does not yet have a sample project transcript.",
                "owner": "Not stated",
                "due_date": "Not stated",
                "source": _source("Kat", "we still don't have the sample project transcript."),
                "confidence": "High",
                "needs_pm_review": False,
                "review_reason": None,
            },
            {
                "type": "Dependency",
                "description": "Getting a sample transcript depends on whether Chloe has something "
                "suitable.",
                "owner": "Izzy",
                "due_date": "Not stated",
                "source": _source("Izzy", "If she doesn't have anything suitable, I'll create an example."),
                "confidence": "Medium",
                "needs_pm_review": False,
                "review_reason": None,
            },
        ]
    },
    indent=2,
)

_SHAREPOINT_KAT = _source("Kat", "For the RAID data, I think we should initially use SharePoint.")
_SHAREPOINT_IZZY = _source("Izzy", "Yes, SharePoint makes sense for the first version. We can revisit Planner later.")
_DEMO = _source("Kat", "We need to have the demo ready for Friday.")
_NO_TRANSCRIPT = _source("Kat", "One issue is that we still don't have the sample project transcript.")
_ANNIE = _source("Annie", "I'll investigate whether the system can detect a transcript automatically "
                          "and let Kazim know what I find.")
_IZZY_CHLOE = _source("Izzy", "I'll ask Chloe for one. If she doesn't have anything suitable, I'll create an example.")


def _answer(text: str, *sources: dict) -> dict:
    return {"category": "answered", "answer": f"[Mock] {text}", "sources": list(sources)}


def _category(name: str) -> dict:
    return {"category": name, "answer": "", "sources": []}


# Example replies chosen by keywords in the question (every keyword must appear;
# first match wins). Quotes are exact text from the sample transcript.md.
MOCK_ANSWERS: tuple[tuple[tuple[str, ...], dict], ...] = (
    (("capital",), _category("out_of_scope")),
    (("ransomware",), _category("out_of_scope")),
    (("worst",), _category("personal_judgement")),
    (("perform",), _category("personal_judgement")),
    (("salary",), _category("not_in_transcript")),
    (("promot",), _category("not_in_transcript")),
    (("planner",), _answer(
        "No. Izzy said SharePoint makes sense for the first version and that the team can revisit "
        "Planner later, so Planner was deferred rather than agreed for now.", _SHAREPOINT_IZZY)),
    (("why", "sharepoint"), _answer(
        "The transcript doesn't give a detailed reason. Kat proposed SharePoint for the RAID data "
        "initially, and Izzy agreed it makes sense for the first version.", _SHAREPOINT_KAT, _SHAREPOINT_IZZY)),
    (("sharepoint",), _answer(
        "The team agreed to use SharePoint for RAID data in the first version. Kat suggested it and "
        "Izzy agreed; Planner may be revisited later.", _SHAREPOINT_KAT, _SHAREPOINT_IZZY)),
    (("missing",), _answer(
        "A few things are still open: nobody was named as owner of the Friday demo, the team doesn't "
        "yet have a sample project transcript, and no dates were given for Annie's or Izzy's tasks.",
        _DEMO, _NO_TRANSCRIPT)),
    (("risk",), _answer(
        "No risks were explicitly discussed. One issue was raised: the team doesn't yet have a sample "
        "project transcript. Izzy will ask Chloe for one, or create an example if Chloe has nothing "
        "suitable.", _NO_TRANSCRIPT, _IZZY_CHLOE)),
    (("action",), _answer(
        "Three actions came up. Annie will investigate whether the system can detect a transcript "
        "automatically and tell Kazim. Izzy will ask Chloe for a sample transcript, or create one if "
        "Chloe has nothing suitable. And the demo needs to be ready for Friday, though nobody was "
        "named as its owner.", _ANNIE, _IZZY_CHLOE, _DEMO)),
    (("demo",), _answer(
        "The transcript doesn't name an owner for the Friday demo. Kat said it needs to be ready for "
        "Friday and should show the working end-to-end flow, but nobody took it on.",
        _DEMO, _source("Kat", "the Friday demo should show the working end-to-end flow."))),
)


def mock_answer(user_prompt: str) -> str:
    """Return the example reply for the question inside a Q&A prompt."""
    questions = re.findall(r"<question>\s*(.*?)\s*</question>", user_prompt, flags=re.DOTALL)
    question = questions[-1].lower() if questions else ""
    for keywords, reply in MOCK_ANSWERS:
        if all(keyword in question for keyword in keywords):
            return json.dumps(reply)
    return json.dumps(_category("not_in_transcript"))


# Reply for each known system prompt: fixed text, or a function of the user prompt.
MOCK_RESPONSES: dict[str, str | Callable[[str], str]] = {
    SUMMARY_SYSTEM_PROMPT: MOCK_SUMMARY,
    EXTRACTION_SYSTEM_PROMPT: MOCK_PROJECT_ITEMS,
    QA_SYSTEM_PROMPT: mock_answer,
}


class MockLLMProvider:
    """An LLMProvider that returns a fixed reply for each known system prompt."""

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        try:
            reply = MOCK_RESPONSES[system_prompt]
        except KeyError:
            raise LLMProviderError(
                "The mock provider has no example reply for this request. "
                "Add one to MOCK_RESPONSES in providers/mock.py."
            ) from None
        return reply(user_prompt) if callable(reply) else reply
