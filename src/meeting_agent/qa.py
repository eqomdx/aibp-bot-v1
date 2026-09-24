"""Answers to questions about a meeting.

Defines the answer shape, turns the model's JSON reply into an Answer,
checks each cited quote against the transcript, and renders answers as
text. Knows nothing about which LLM produced the reply.
"""

from dataclasses import dataclass, field

from meeting_agent.errors import QuestionError
from meeting_agent.llm_output import load_json_reply, quote_in_text


@dataclass(frozen=True)
class Source:
    quote: str
    # Set by the application, not the model: was the quote found in the transcript?
    verified: bool = False


@dataclass(frozen=True)
class Answer:
    question: str
    answer: str
    found_in_transcript: bool
    sources: list[Source] = field(default_factory=list)

    @property
    def is_supported(self) -> bool:
        """True if the answer cites at least one quote and every quote was found."""
        return bool(self.sources) and all(source.verified for source in self.sources)


@dataclass(frozen=True)
class Turn:
    """One earlier question and answer, passed back in for follow-up questions."""

    question: str
    answer: str


def parse_answer(text: str, question: str, transcript: str) -> Answer:
    """Parse the model's JSON reply and verify its quotes, or raise QuestionError."""
    data = load_json_reply(text, "question answering", QuestionError)
    if not isinstance(data, dict):
        raise QuestionError("The model's answer was not a JSON object.")

    answer = str(data.get("answer") or "").strip()
    if not answer:
        raise QuestionError("The model's reply did not contain an answer.")

    found = data.get("found_in_transcript")
    if not isinstance(found, bool):
        raise QuestionError('The model\'s reply is missing "found_in_transcript" (true or false).')

    raw_sources = data.get("sources") or []
    if not isinstance(raw_sources, list):
        raise QuestionError('The model\'s "sources" must be a list of quotes.')

    quotes = [str(quote).strip() for quote in raw_sources if str(quote or "").strip()]
    sources = [Source(quote, verified=quote_in_text(quote, transcript)) for quote in quotes]
    return Answer(question=question, answer=answer, found_in_transcript=found, sources=sources)


def answer_to_text(answer: Answer) -> str:
    """Render an answer for a terminal or chat window."""
    lines = [answer.answer]

    if not answer.found_in_transcript:
        return "\n".join(lines) + "\n"

    if answer.sources:
        lines += ["", "Sources:"]
        for source in answer.sources:
            flag = "" if source.verified else "  (NOT FOUND IN TRANSCRIPT)"
            lines.append(f'  - "{source.quote}"{flag}')

    if not answer.is_supported:
        lines += ["", "Warning: this answer is not backed by a verified quote from the transcript. "
                      "Check it before relying on it."]
    return "\n".join(lines) + "\n"
