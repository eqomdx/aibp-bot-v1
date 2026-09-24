"""Wiring shared by every interface (the process and ask commands today;
Teams, Copilot Studio or a web API later)."""

import sys

from meeting_agent.meeting_service import MeetingService
from meeting_agent.providers import create_provider


def build_service(provider_name: str) -> MeetingService:
    """Wire MeetingService to the named LLM provider."""
    return MeetingService(create_provider(provider_name))


def use_utf8_console() -> None:
    """Stop non-ASCII model output from crashing a legacy Windows console."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
