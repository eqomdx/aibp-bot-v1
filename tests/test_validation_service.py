"""validation_service.validate_extraction: the pure function behind POST /validate."""

import json
from datetime import date

import pytest

from conftest import SAMPLE_TRANSCRIPT_PATH
from meeting_agent.errors import ExtractionError, TranscriptError
from meeting_agent.main import run
from meeting_agent.providers.mock import MOCK_PROJECT_ITEMS
from meeting_agent.validation_service import validate_extraction

TRANSCRIPT = "Kat: Annie, can you update the RAID log by Friday?\nAnnie: Yep, I'll do that."
ITEM = {
    "type": "Action", "title": "Update RAID log", "description": "Update the RAID log.", "owner": "Annie",
    "due_date": "Friday", "source": {"speaker": "Annie", "quote": "Yep, I'll do that.", "timestamp": None},
    "confidence": "High",
}


def test_accepts_object_list_and_text_forms():
    forms = [{"items": [ITEM]}, [ITEM], json.dumps({"items": [ITEM]})]

    results = [validate_extraction(TRANSCRIPT, form, "AIBP", date(2026, 9, 24)) for form in forms]

    assert results[0] == results[1] == results[2]
    assert results[0]["items"][0]["due_date"] == "2026-09-25"


def test_project_is_trimmed_and_blank_means_none():
    assert validate_extraction(TRANSCRIPT, [ITEM], "  AIBP  ")["project"] == "AIBP"
    assert validate_extraction(TRANSCRIPT, [ITEM], "   ")["project"] is None


def test_explicit_meeting_date_beats_the_transcript_header():
    result = validate_extraction("Date: 2026-01-05\n" + TRANSCRIPT, [ITEM], "AIBP", date(2026, 9, 24))

    assert result["meeting_date"] == "2026-09-24"


@pytest.mark.parametrize("transcript", ["", None, "  "])
def test_unusable_transcript_raises(transcript):
    with pytest.raises(TranscriptError):
        validate_extraction(transcript, [ITEM])


def test_schema_errors_raise_extraction_error():
    with pytest.raises(ExtractionError, match="Allowed types"):
        validate_extraction(TRANSCRIPT, [{**ITEM, "type": "Task"}])


def test_same_result_as_the_local_extraction_path(tmp_path, monkeypatch):
    """Pattern A (local model) and Pattern B (Copilot + /validate) share one validation pipeline."""
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    transcript_file = tmp_path / "transcript.md"
    transcript_file.write_text(SAMPLE_TRANSCRIPT_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    local = run("extract", transcript_file, tmp_path, "mock", date(2026, 9, 23), "AIBP")
    remote = validate_extraction(transcript_file.read_text(encoding="utf-8"), MOCK_PROJECT_ITEMS,
                                 "AIBP", date(2026, 9, 23))

    assert remote["items"] == [item.to_dict() for item in local.items]
    assert remote["meetingSummary"] == local.extraction_summary
