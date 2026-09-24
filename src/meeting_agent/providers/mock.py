"""Mock provider for development and tests without live credentials.

Returns a fixed reply for each known system prompt and makes no network
calls. The replies are examples written for the sample transcript.md, not
readings of whatever transcript is supplied, and say so where they can.
"""

import json
import re
from collections.abc import Callable

from meeting_agent.errors import LLMProviderError
from meeting_agent.prompts import EXTRACTION_SYSTEM_PROMPT, QA_SYSTEM_PROMPT, SUMMARY_SYSTEM_PROMPT

MOCK_SUMMARY = """\
# Meeting Summary

## Overview
_Mock provider output: fixed example text, not generated from the supplied transcript._ The team met to prepare for a Friday demo, agreed to use SharePoint for RAID data in the first version, and noted that a sample project transcript is still outstanding.

## Key Discussion Points
- The demo needs to be ready for Friday.
- Whether the system can detect a transcript automatically.
- SharePoint was proposed for RAID data initially; Planner may be revisited later.
- The team does not yet have a sample project transcript.

## Decisions
- SharePoint will be used for RAID data in the first version (proposed by Kat, agreed by Izzy).

## Actions Mentioned
- Annie: investigate whether the system can detect a transcript automatically and tell Kazim what she finds.
- Izzy: ask Chloe for a sample project transcript; if nothing suitable is available, create an example.

## Risks / Issues Mentioned
- Issue: no sample project transcript is available yet.

## Open Questions
- Whether Planner will be used in a later version.
- Whether Chloe has a suitable sample transcript.
"""

# Sources are exact quotes from the sample transcript.md, so they verify
# against it; against any other transcript they will be flagged as not found.
MOCK_PROJECT_ITEMS = json.dumps(
    {
        "items": [
            {
                "type": "action",
                "description": "Have the demo ready.",
                "owner": None,
                "due_date": "Friday",
                "source": "We need to have the demo ready for Friday.",
                "confidence": "medium",
            },
            {
                "type": "action",
                "description": "Investigate whether the system can detect a transcript "
                "automatically and let Kazim know the findings.",
                "owner": "Annie",
                "due_date": None,
                "source": "I'll investigate whether the system can detect a transcript "
                "automatically and let Kazim know what I find.",
                "confidence": "high",
            },
            {
                "type": "action",
                "description": "Ask Chloe for a sample project transcript; if she has nothing "
                "suitable, create an example.",
                "owner": "Izzy",
                "due_date": None,
                "source": "I'll ask Chloe for one. If she doesn't have anything suitable, "
                "I'll create an example.",
                "confidence": "high",
            },
            {
                "type": "decision",
                "description": "Use SharePoint for RAID data in the first version; Planner may "
                "be revisited later.",
                "owner": None,
                "due_date": None,
                "source": "Yes, SharePoint makes sense for the first version.",
                "confidence": "medium",
            },
            {
                "type": "issue",
                "description": "The team does not yet have a sample project transcript.",
                "owner": None,
                "due_date": None,
                "source": "we still don't have the sample project transcript.",
                "confidence": "high",
            },
            {
                "type": "dependency",
                "description": "Getting a sample transcript depends on whether Chloe has "
                "something suitable.",
                "owner": "Izzy",
                "due_date": None,
                "source": "If she doesn't have anything suitable, I'll create an example.",
                "confidence": "medium",
            },
        ]
    },
    indent=2,
)

# Example answers for the questions in the project brief, chosen by the first
# keyword found in the question. Quotes are exact text from the sample transcript.
MOCK_ANSWERS = (
    (
        "sharepoint",
        {
            "answer": "[Mock] The team agreed to use SharePoint for RAID data in the first version. "
            "Kat suggested it and Izzy agreed; Planner may be revisited later.",
            "found_in_transcript": True,
            "sources": [
                "For the RAID data, I think we should initially use SharePoint.",
                "Yes, SharePoint makes sense for the first version. We can revisit Planner later.",
            ],
        },
    ),
    (
        "risk",
        {
            "answer": "[Mock] No risks were explicitly discussed. One issue was raised: the team "
            "does not yet have a sample project transcript. Izzy will ask Chloe for one, or "
            "create an example if Chloe has nothing suitable.",
            "found_in_transcript": True,
            "sources": [
                "One issue is that we still don't have the sample project transcript.",
                "I'll ask Chloe for one. If she doesn't have anything suitable, I'll create an example.",
            ],
        },
    ),
    (
        "demo",
        {
            "answer": "[Mock] The transcript does not name an owner for the demo. Kat said it needs "
            "to be ready for Friday, but nobody took it on.",
            "found_in_transcript": True,
            "sources": ["We need to have the demo ready for Friday."],
        },
    ),
)

MOCK_NO_ANSWER = {
    "answer": "[Mock] The mock provider only has example answers for questions about "
    "SharePoint, risks or the demo. Switch to LLM_PROVIDER=azure for real answers.",
    "found_in_transcript": False,
    "sources": [],
}


def mock_answer(user_prompt: str) -> str:
    """Return the example answer for the question inside a Q&A prompt."""
    match = re.search(r"<question>\s*(.*?)\s*</question>", user_prompt, flags=re.DOTALL)
    question = match.group(1).lower() if match else ""
    for keyword, answer in MOCK_ANSWERS:
        if keyword in question:
            return json.dumps(answer)
    return json.dumps(MOCK_NO_ANSWER)


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
