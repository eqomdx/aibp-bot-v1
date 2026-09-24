"""Meeting-processing logic.

Knows about meetings and prompts, not about Azure, authentication or any user
interface. Every interface (CLI today; Copilot Studio, Teams or a web API
later) should call this service rather than an LLM directly, so they all get
the same prompts, checks and safeguards.
"""

from collections.abc import Sequence
from datetime import date

from meeting_agent.errors import QuestionError, SummarisationError
from meeting_agent.project_items import ProjectItem, deduplicate, parse_project_items
from meeting_agent.prompts import (
    EXTRACTION_SYSTEM_PROMPT,
    QA_SYSTEM_PROMPT,
    SUMMARY_SYSTEM_PROMPT,
    build_extraction_prompt,
    build_question_prompt,
    build_summary_prompt,
)
from meeting_agent.providers.base import LLMProvider
from meeting_agent.qa import Answer, Turn, parse_answer, refusal
from meeting_agent.review import apply_review_checks
from meeting_agent.safety import screen_question


class MeetingService:
    def __init__(self, provider: LLMProvider):
        self.provider = provider

    def summarise(self, transcript: str) -> str:
        """Return a Markdown project-management summary of the transcript."""
        summary = self.provider.generate(
            system_prompt=SUMMARY_SYSTEM_PROMPT,
            user_prompt=build_summary_prompt(transcript),
        )
        summary = (summary or "").strip()
        if not summary:
            raise SummarisationError("The model returned an empty summary. Try running again.")
        return summary

    def extract_items(self, transcript: str, meeting_date: date | None = None) -> list[ProjectItem]:
        """Return the meeting's Actions, Decisions, Risks, Issues, Dependencies and Assumptions.

        After the model replies, the application merges duplicates, checks each
        item's evidence against the transcript, resolves relative due dates when
        `meeting_date` is known, and sets needs_pm_review with reasons.
        """
        reply = self.provider.generate(
            system_prompt=EXTRACTION_SYSTEM_PROMPT,
            user_prompt=build_extraction_prompt(transcript),
        )
        items = deduplicate(parse_project_items(reply))
        return apply_review_checks(items, transcript, meeting_date)

    def answer_question(
        self, transcript: str, question: str, history: Sequence[Turn] = ()
    ) -> Answer:
        """Answer a question about the meeting from the transcript alone.

        Requests for secrets or external changes are refused in code without
        calling the model. `history` holds earlier turns so follow-ups make
        sense; the service keeps no state itself.
        """
        question = (question or "").strip()
        if not question:
            raise QuestionError("The question is empty.")

        category = screen_question(question)
        if category:
            return refusal(question, category)

        reply = self.provider.generate(
            system_prompt=QA_SYSTEM_PROMPT,
            user_prompt=build_question_prompt(transcript, question, history),
        )
        return parse_answer(reply, question, transcript)
