"""Command-line interface: load transcript -> MeetingService -> save outputs.

This is one interface onto MeetingService. Later interfaces (Copilot Studio,
Teams, a web API) should wire up the service the same way, via build_service().

Usage:
    python -m meeting_agent.main [path/to/transcript.md] [-o output/folder]
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from meeting_agent.app import build_service, use_utf8_console
from meeting_agent.config import get_provider_name, load_environment
from meeting_agent.errors import MeetingAgentError
from meeting_agent.missing_information import InformationGap, gaps_to_markdown
from meeting_agent.output import save_json, save_markdown
from meeting_agent.project_items import ProjectItem, items_to_markdown
from meeting_agent.transcript import load_transcript

DEFAULT_TRANSCRIPT = "transcript.md"
SUMMARY_FILENAME = "summary.md"
ITEMS_JSON_FILENAME = "project_items.json"
ITEMS_MARKDOWN_FILENAME = "project_items.md"


@dataclass
class MeetingOutputs:
    summary: str
    items: list[ProjectItem]
    gaps: list[InformationGap]
    items_markdown: str
    files: list[Path]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m meeting_agent.main",
        description="Summarise a meeting transcript and extract its project items.",
    )
    parser.add_argument(
        "transcript",
        nargs="?",
        default=DEFAULT_TRANSCRIPT,
        help=f"Path to the transcript Markdown file (default: {DEFAULT_TRANSCRIPT})",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        help="Folder for the output files (default: the transcript's folder)",
    )
    return parser.parse_args(argv)


def run(transcript_path: Path, output_dir: Path, provider_name: str) -> MeetingOutputs:
    """Process one transcript file and save every output. Nothing is written if any step fails."""
    transcript = load_transcript(transcript_path)
    service = build_service(provider_name)

    summary = service.summarise(transcript)
    items = service.extract_items(transcript)
    gaps = service.find_missing_information(items)
    items_markdown = items_to_markdown(items) + "\n" + gaps_to_markdown(gaps)

    items_document = {
        "transcript": transcript_path.name,
        "items": [item.to_dict() for item in items],
        "missing_information": [gap.to_dict() for gap in gaps],
    }
    files = [
        save_markdown(output_dir / SUMMARY_FILENAME, summary),
        save_json(output_dir / ITEMS_JSON_FILENAME, items_document),
        save_markdown(output_dir / ITEMS_MARKDOWN_FILENAME, items_markdown),
    ]
    return MeetingOutputs(summary, items, gaps, items_markdown, files)


def main(argv: list[str] | None = None) -> int:
    use_utf8_console()
    args = parse_args(argv)
    load_environment()

    transcript_path = Path(args.transcript)
    output_dir = Path(args.output_dir) if args.output_dir else transcript_path.parent

    try:
        provider_name = get_provider_name()
        print(f"Processing {transcript_path} with the '{provider_name}' provider ...", flush=True)
        outputs = run(transcript_path, output_dir, provider_name)
    except MeetingAgentError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Saved:")
    for path in outputs.files:
        print(f"  {path}")
    print()
    print(outputs.summary)
    print()
    print(outputs.items_markdown, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
