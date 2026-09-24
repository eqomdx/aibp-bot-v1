"""Meeting-processing logic.

Knows about meetings and prompts, not about Azure or authentication. Any
interface (CLI today; Copilot Studio, Teams or a web API later) should call
this service rather than an LLM directly.
"""

from collections.abc import Sequence

from meeting_agent.errors import QuestionError, SummarisationError
from meeting_agent.missing_information import InformationGap, find_missing_information
from meeting_agent.project_items import ProjectItem, parse_project_items, verify_sources
from meeting_agent.prompts import (
    EXTRACTION_SYSTEM_PROMPT,
    QA_SYSTEM_PROMPT,
    SUMMARY_SYSTEM_PROMPT,
    build_extraction_prompt,
    build_question_prompt,
    build_summary_prompt,
)
from meeting_agent.providers.base import LLMProvider
from meeting_agent.qa import Answer, Turn, parse_answer


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

    def extract_items(self, transcript: str) -> list[ProjectItem]:
        """Return the transcript's actions, decisions, RAID items, dependencies and assumptions.

        Each item's source quote is checked against the transcript; items whose
        quote cannot be found are kept but marked source_verified=False.
        """
        reply = self.provider.generate(
            system_prompt=EXTRACTION_SYSTEM_PROMPT,
            user_prompt=build_extraction_prompt(transcript),
        )
        return verify_sources(parse_project_items(reply), transcript)

    def answer_question(
        self, transcript: str, question: str, history: Sequence[Turn] = ()
    ) -> Answer:
        """Answer a question about the meeting from the transcript alone.

        `history` holds earlier turns of the same conversation so follow-ups
        ("who owns it?") make sense. The service keeps no state itself: each
        interface (CLI, Teams, Copilot Studio) owns its own conversation.
        """
        question = (question or "").strip()
        if not question:
            raise QuestionError("The question is empty.")

        reply = self.provider.generate(
            system_prompt=QA_SYSTEM_PROMPT,
            user_prompt=build_question_prompt(transcript, question, history),
        )
        return parse_answer(reply, question, transcript)

    def find_missing_information(self, items: list[ProjectItem]) -> list[InformationGap]:
        """Return what still needs chasing: missing owners, due dates, unverified sources.

        Rule-based; makes no LLM call.
        """
        return find_missing_information(items)
