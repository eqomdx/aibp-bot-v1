"""Chat interface: ask questions about a meeting.

Usage (either form):
    python -m meeting_agent.main chat [transcript.md] [-q "question" ...]
    python -m meeting_agent.ask       [transcript.md] [-q "question" ...]

Without -q it runs interactively until 'exit'. This interface owns the
conversation history and passes it to MeetingService.answer_question(),
which stays stateless and applies all safeguards.
"""

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from meeting_agent.app import build_service, use_utf8_console
from meeting_agent.config import get_provider_name, load_environment
from meeting_agent.errors import MeetingAgentError
from meeting_agent.meeting_service import MeetingService
from meeting_agent.qa import Turn, answer_to_text
from meeting_agent.transcript import load_transcript

DEFAULT_TRANSCRIPT = "transcript.md"
EXIT_COMMANDS = {"exit", "quit", "q"}
PROMPT = "> "


class Conversation:
    """One Q&A session over one transcript. Remembers turns for follow-up questions."""

    def __init__(self, service: MeetingService, transcript: str):
        self.service = service
        self.transcript = transcript
        self.history: list[Turn] = []

    def ask(self, question: str) -> str:
        """Answer a question and return it as text. Raises MeetingAgentError on failure."""
        answer = self.service.answer_question(self.transcript, question, self.history)
        self.history.append(Turn(question=answer.question, answer=answer.answer))
        return answer_to_text(answer)


def ask_questions(conversation: Conversation, questions: list[str]) -> int:
    """Answer each question in order. Returns 1 if any failed, else 0."""
    exit_code = 0
    for question in questions:
        print(f"> {question}\n")
        try:
            print(conversation.ask(question))
        except MeetingAgentError as exc:
            print(f"Error: {exc}\n", file=sys.stderr)
            exit_code = 1
    return exit_code


def interactive(conversation: Conversation, read: Callable[[str], str] = input) -> int:
    """Read questions until 'exit' or end of input. An error doesn't end the session."""
    print("Ask a question about the meeting.\nType 'exit' to leave.\n")
    while True:
        try:
            question = read(PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not question:
            continue
        if question.lower() in EXIT_COMMANDS:
            return 0
        print()
        try:
            print(conversation.ask(question))
        except MeetingAgentError as exc:
            print(f"Error: {exc}\n", file=sys.stderr)


def chat(transcript_path: Path, questions: list[str] | None, read: Callable[[str], str] = input) -> int:
    """Load the meeting, then answer `questions`, or run interactively if there are none."""
    try:
        provider_name = get_provider_name()
        transcript = load_transcript(transcript_path)
        conversation = Conversation(build_service(provider_name), transcript)
    except MeetingAgentError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Meeting loaded: {transcript_path} (provider: {provider_name}).\n")
    if questions:
        return ask_questions(conversation, questions)
    return interactive(conversation, read)


def main(argv: list[str] | None = None, read: Callable[[str], str] = input) -> int:
    use_utf8_console()
    parser = argparse.ArgumentParser(prog="python -m meeting_agent.ask",
                                     description="Ask questions about a meeting transcript.")
    parser.add_argument("transcript", nargs="?", default=DEFAULT_TRANSCRIPT)
    parser.add_argument("-q", "--question", action="append",
                        help="Question to answer; repeat for follow-ups. Omit for interactive mode.")
    args = parser.parse_args(argv)
    load_environment()
    return chat(Path(args.transcript), args.question, read)


if __name__ == "__main__":
    sys.exit(main())
