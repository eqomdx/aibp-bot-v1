from datetime import date

import pytest

from meeting_agent.errors import TranscriptError
from meeting_agent.transcript import detect_meeting_date, load_transcript


def test_valid_transcript_loads(tmp_path):
    path = tmp_path / "transcript.md"
    path.write_text("# Meeting\n\nKat: We need the demo for Friday.\n", encoding="utf-8")

    text = load_transcript(path)

    assert "Kat: We need the demo for Friday." in text


def test_surrounding_whitespace_is_trimmed(tmp_path):
    path = tmp_path / "transcript.md"
    path.write_text("\n\n  Kat: Hello.  \n\n", encoding="utf-8")

    assert load_transcript(path) == "Kat: Hello."


def test_utf8_bom_is_ignored(tmp_path):
    path = tmp_path / "transcript.md"
    path.write_text("Kat: Hello.", encoding="utf-8-sig")

    assert load_transcript(path) == "Kat: Hello."


def test_missing_transcript_fails(tmp_path):
    missing = tmp_path / "transcript.md"

    with pytest.raises(TranscriptError) as excinfo:
        load_transcript(missing)

    assert str(excinfo.value) == f"Transcript file '{missing}' was not found."


def test_directory_is_rejected(tmp_path):
    with pytest.raises(TranscriptError, match="is not a file"):
        load_transcript(tmp_path)


@pytest.mark.parametrize(
    "content",
    ["", "   \n\n\t\n", "# Project Meeting Transcript\n\n## Notes\n"],
    ids=["empty", "whitespace-only", "headings-only"],
)
def test_empty_transcript_fails(tmp_path, content):
    path = tmp_path / "transcript.md"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(TranscriptError) as excinfo:
        load_transcript(path)

    assert str(excinfo.value) == "Transcript contains no usable text."


def test_non_utf8_transcript_is_rejected(tmp_path):
    path = tmp_path / "transcript.md"
    path.write_bytes(b"Kat: caf\xe9 \xff\xfe")

    with pytest.raises(TranscriptError, match="UTF-8"):
        load_transcript(path)


# --- meeting date detection ----------------------------------------------

@pytest.mark.parametrize(
    "header",
    ["Date: 2026-09-23", "**Date:** 2026-09-23", "Meeting date: 2026-09-23", "- date - 2026-09-23"],
)
def test_meeting_date_is_read_from_header(header):
    text = f"# Project Meeting\n{header}\n\nKat: Hello."

    assert detect_meeting_date(text) == date(2026, 9, 23)


def test_no_date_header_gives_none():
    assert detect_meeting_date("Kat: We need the demo for Friday.") is None


def test_dates_deep_in_the_transcript_are_ignored():
    text = "\n".join(["Kat: hi."] * 20 + ["Date: 2026-09-23"])

    assert detect_meeting_date(text) is None


def test_invalid_header_date_gives_none():
    assert detect_meeting_date("Date: 2026-02-30\nKat: hi.") is None
