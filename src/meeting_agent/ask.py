"""Command-line interface for asking questions about a meeting.

Usage:
    python -m meeting_agent.ask [transcript.md] -q "What did we decide about SharePoint?"
    python -m meeting_agent.ask [transcript.md]          (interactive; type 'exit' to stop)

This interface owns the conversation history and passes it to
MeetingService.answer_question(), which stays stateless.
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
PROMPT = "Question> "


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m meeting_agent.ask",
        description="Ask questions about a meeting transcript.",
    )
    parser.add_argument(
        "transcript",
        nargs="?",
        default=DEFAULT_TRANSCRIPT,
        help=f"Path to the transcript Markdown file (default: {DEFAULT_TRANSCRIPT})",
    )
    parser.add_argument(
        "-q",
        "--question",
        action="append",
        help="A question to answer. Repeat for follow-ups. Omit to start an interactive session.",
    )
    return parser.parse_args(argv)


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
        print(f"Q: {question}")
        try:
            print(conversation.ask(question))
        except MeetingAgentError as exc:
            print(f"Error: {exc}\n", file=sys.stderr)
            exit_code = 1
    return exit_code


def interactive(conversation: Conversation, read: Callable[[str], str] = input) -> int:
    """Read questions until the user types exit/quit or ends input. Errors don't end the session."""
    print("Ask a question about the meeting. Type 'exit' to stop.\n")
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
        try:
            print(conversation.ask(question))
        except MeetingAgentError as exc:
            print(f"Error: {exc}\n", file=sys.stderr)


def main(argv: list[str] | None = None, read: Callable[[str], str] = input) -> int:
    use_utf8_console()
    args = parse_args(argv)
    load_environment()

    transcript_path = Path(args.transcript)
    try:
        provider_name = get_provider_name()
        transcript = load_transcript(transcript_path)
        conversation = Conversation(build_service(provider_name), transcript)
    except MeetingAgentError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Answering from {transcript_path} with the '{provider_name}' provider.\n")
    if args.question:
        return ask_questions(conversation, args.question)
    return interactive(conversation, read)


if __name__ == "__main__":
    sys.exit(main())
