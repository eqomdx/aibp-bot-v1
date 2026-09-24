"""Answers to questions about a meeting.

Defines the answer shape, turns the model's JSON reply into an Answer,
checks each cited quote against the transcript, enforces fixed wording for
refusals, and renders answers as text.
"""

from dataclasses import dataclass

from meeting_agent.errors import QuestionError
from meeting_agent.evidence import Evidence, check_evidence, parse_evidence
from meeting_agent.llm_output import load_json_reply
from meeting_agent.prompts import QA_CATEGORIES
from meeting_agent.safety import ANSWERED, CANNED_REPLIES, SECRET_REQUEST, reveals_instructions


@dataclass(frozen=True)
class Answer:
    question: str
    category: str
    answer: str
    sources: tuple[Evidence, ...] = ()

    @property
    def found_in_transcript(self) -> bool:
        return self.category == ANSWERED

    @property
    def is_supported(self) -> bool:
        """True if the answer cites at least one quote and every quote checked out."""
        return bool(self.sources) and all(source.verified for source in self.sources)


@dataclass(frozen=True)
class Turn:
    """One earlier question and answer, passed back in for follow-up questions."""

    question: str
    answer: str


def refusal(question: str, category: str) -> Answer:
    """An answer with the fixed reply for a non-answer category."""
    return Answer(question=question, category=category, answer=CANNED_REPLIES[category])


def parse_answer(text: str, question: str, transcript: str) -> Answer:
    """Parse the model's JSON reply into a checked Answer, or raise QuestionError."""
    data = load_json_reply(text, "question answering", QuestionError)
    if not isinstance(data, dict):
        raise QuestionError("The model's answer was not a JSON object.")

    category = str(data.get("category") or "").strip().lower()
    if category not in QA_CATEGORIES:
        raise QuestionError(f"The model's reply has an unknown category '{category}'.")
    if category != ANSWERED:
        return refusal(question, category)

    answer = str(data.get("answer") or "").strip()
    if not answer:
        raise QuestionError("The model's reply did not contain an answer.")
    if reveals_instructions(answer):
        return refusal(question, SECRET_REQUEST)

    raw_sources = data.get("sources") or []
    if not isinstance(raw_sources, list):
        raise QuestionError('The model\'s "sources" must be a list.')
    sources = tuple(
        check_evidence(evidence, transcript)
        for evidence in map(parse_evidence, raw_sources)
        if evidence.quote
    )
    return Answer(question=question, category=category, answer=answer, sources=sources)


def answer_to_text(answer: Answer) -> str:
    """Render an answer for a terminal or chat window."""
    lines = [answer.answer]
    if not answer.found_in_transcript:
        return "\n".join(lines) + "\n"

    if answer.sources:
        lines += ["", "Sources:"]
        for source in answer.sources:
            flag = "" if source.verified else "  (NOT FOUND IN TRANSCRIPT)"
            lines.append(f"  - {source.to_text()}{flag}")

    if not answer.is_supported:
        lines += ["", "Warning: this answer is not backed by a verified quote from the transcript. "
                      "Check it before relying on it."]
    return "\n".join(lines) + "\n"
