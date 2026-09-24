import pytest

from meeting_agent.errors import TranscriptError
from meeting_agent.transcript import load_transcript


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
