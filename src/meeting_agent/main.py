"""Command-line interface onto MeetingService.

Usage:
    python -m meeting_agent.main summarise [transcript.md] [-o folder]
    python -m meeting_agent.main extract   [transcript.md] [-o folder] [--meeting-date YYYY-MM-DD]
    python -m meeting_agent.main chat      [transcript.md] [-q "question" ...]
    python -m meeting_agent.main [transcript.md]          (summary and extraction together)

This module only parses arguments, wires up the service and writes files.
Meeting logic lives in MeetingService; other interfaces (Teams, Copilot
Studio, a web API) should wire it up the same way, via app.build_service().
"""

import argparse
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from meeting_agent import ask
from meeting_agent.app import build_service, use_utf8_console
from meeting_agent.config import get_provider_name, load_environment
from meeting_agent.errors import MeetingAgentError
from meeting_agent.output import save_json, save_markdown
from meeting_agent.project_items import ProjectItem, items_to_markdown
from meeting_agent.transcript import detect_meeting_date, load_transcript

DEFAULT_TRANSCRIPT = "transcript.md"
SUMMARY_FILENAME = "summary.md"
ITEMS_JSON_FILENAME = "project_items.json"
ITEMS_MARKDOWN_FILENAME = "project_items.md"

COMMANDS = ("summarise", "extract", "chat", "all")
ALIASES = {"summarize": "summarise"}


@dataclass
class MeetingOutputs:
    summary: str | None = None
    items: list[ProjectItem] | None = None
    items_markdown: str | None = None
    meeting_date: date | None = None
    files: list[Path] = field(default_factory=list)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in (*COMMANDS, *ALIASES, "-h", "--help"):
        argv.insert(0, "all")  # bare "main transcript.md" keeps its original meaning

    parser = argparse.ArgumentParser(
        prog="python -m meeting_agent.main",
        description="Project-management meeting agent: summarise, extract items, or chat about a transcript.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    specs = {
        "summarise": ("Write a meeting summary (summary.md).", ["summarize"]),
        "extract": ("Extract Actions, Decisions and RAID items (project_items.json / .md).", []),
        "chat": ("Ask questions about the meeting, one-shot (-q) or interactively.", []),
        "all": ("Summary and extraction together (the default).", []),
    }
    for name, (help_text, aliases) in specs.items():
        command = commands.add_parser(name, aliases=aliases, help=help_text, description=help_text)
        command.add_argument("transcript", nargs="?", default=DEFAULT_TRANSCRIPT,
                             help=f"Transcript Markdown file (default: {DEFAULT_TRANSCRIPT})")
        if name == "chat":
            command.add_argument("-q", "--question", action="append",
                                 help="Question to answer; repeat for follow-ups. Omit for interactive mode.")
            continue
        command.add_argument("-o", "--output-dir", help="Folder for output files (default: the transcript's folder)")
        if name in ("extract", "all"):
            command.add_argument("--meeting-date", type=_iso_date,
                                 help="Meeting date (YYYY-MM-DD), used to resolve 'tomorrow' or 'Friday'. "
                                      "Default: a 'Date:' line at the top of the transcript, if any.")

    args = parser.parse_args(argv)
    args.command = ALIASES.get(args.command, args.command)
    return args


def run(
    command: str,
    transcript_path: Path,
    output_dir: Path,
    provider_name: str,
    meeting_date: date | None = None,
) -> MeetingOutputs:
    """Run summarise, extract or all for one transcript. Nothing is written if any step fails."""
    transcript = load_transcript(transcript_path)
    service = build_service(provider_name)
    outputs = MeetingOutputs(meeting_date=meeting_date or detect_meeting_date(transcript))

    if command in ("summarise", "all"):
        outputs.summary = service.summarise(transcript)
    if command in ("extract", "all"):
        outputs.items = service.extract_items(transcript, outputs.meeting_date)
        outputs.items_markdown = items_to_markdown(outputs.items)

    if outputs.summary is not None:
        outputs.files.append(save_markdown(output_dir / SUMMARY_FILENAME, outputs.summary))
    if outputs.items is not None:
        document = {
            "transcript": transcript_path.name,
            "meeting_date": outputs.meeting_date.isoformat() if outputs.meeting_date else None,
            "items": [item.to_dict() for item in outputs.items],
        }
        outputs.files.append(save_json(output_dir / ITEMS_JSON_FILENAME, document))
        outputs.files.append(save_markdown(output_dir / ITEMS_MARKDOWN_FILENAME, outputs.items_markdown))
    return outputs


def main(argv: list[str] | None = None, read=input) -> int:
    use_utf8_console()
    args = parse_args(argv)
    load_environment()

    if args.command == "chat":
        return ask.chat(Path(args.transcript), args.question, read)

    transcript_path = Path(args.transcript)
    output_dir = Path(args.output_dir) if args.output_dir else transcript_path.parent
    try:
        provider_name = get_provider_name()
        print(f"Processing {transcript_path} with the '{provider_name}' provider ...", flush=True)
        outputs = run(args.command, transcript_path, output_dir, provider_name,
                      getattr(args, "meeting_date", None))
    except MeetingAgentError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Saved:")
    for path in outputs.files:
        print(f"  {path}")
    for block in (outputs.summary, outputs.items_markdown):
        if block:
            print()
            print(block.rstrip())
    return 0


def _iso_date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{text}' is not a date in YYYY-MM-DD form.") from None


if __name__ == "__main__":
    sys.exit(main())
