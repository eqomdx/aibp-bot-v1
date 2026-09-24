"""Loading and validating meeting transcripts.

Knows nothing about LLMs. Later phases (multiple meetings, a knowledge
store) should reuse load_transcript rather than reading files themselves.
"""

from pathlib import Path

from meeting_agent.errors import TranscriptError


def load_transcript(path: str | Path) -> str:
    """Read a transcript file and return its text.

    Raises TranscriptError if the file is missing, unreadable, or has no
    usable content.
    """
    path = Path(path)

    if not path.exists():
        raise TranscriptError(f"Transcript file '{path}' was not found.")
    if not path.is_file():
        raise TranscriptError(f"Transcript path '{path}' is not a file.")

    try:
        # utf-8-sig tolerates the byte-order mark some Windows editors add.
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise TranscriptError(
            f"Transcript is not valid UTF-8 text: {path}. Re-save it as UTF-8."
        ) from None
    except OSError as exc:
        raise TranscriptError(f"Could not read transcript {path}: {exc.strerror}") from None

    validate_transcript(text)
    return text.strip()


def validate_transcript(text: str) -> None:
    """Raise TranscriptError unless the text contains something to summarise.

    Blank lines and Markdown headings alone do not count as content.
    """
    content_lines = [
        line
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not content_lines:
        raise TranscriptError("Transcript contains no usable text.")
