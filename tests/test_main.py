"""CLI: summarise, extract, chat and the default run, end to end with the mock provider."""

import json

import pytest

from conftest import SAMPLE_TRANSCRIPT_PATH
from meeting_agent import main as cli
from meeting_agent.errors import LLMProviderError
from meeting_agent.meeting_service import MeetingService
from meeting_agent.providers.mock import MOCK_SUMMARY

SUMMARY = "summary.md"
ITEM_FILES = ["project_items.json", "project_items.md"]
ALL_FILES = [SUMMARY, *ITEM_FILES]


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    """Stop main() from loading the developer's real .env file."""
    monkeypatch.setattr(cli, "load_environment", lambda: None)


@pytest.fixture
def transcript_file(tmp_path):
    """A copy of the sample transcript, so the mock's quotes verify."""
    path = tmp_path / "transcript.md"
    path.write_text(SAMPLE_TRANSCRIPT_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    return path


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")


@pytest.fixture
def use_provider(monkeypatch, mock_env):
    def install(provider):
        monkeypatch.setattr(cli, "build_service", lambda name: MeetingService(provider))
        return provider

    return install


def written(folder):
    return [name for name in ALL_FILES if (folder / name).exists()]


# --- commands ----------------------------------------------------------------

def test_summarise_writes_only_the_summary(mock_env, transcript_file, capsys):
    assert cli.main(["summarise", str(transcript_file)]) == 0

    assert written(transcript_file.parent) == [SUMMARY]
    assert (transcript_file.parent / SUMMARY).read_text(encoding="utf-8") == MOCK_SUMMARY
    assert "## Open Questions" in capsys.readouterr().out


def test_summarize_spelling_also_works(mock_env, transcript_file):
    assert cli.main(["summarize", str(transcript_file)]) == 0
    assert written(transcript_file.parent) == [SUMMARY]


def test_extract_writes_only_the_items(mock_env, transcript_file, capsys):
    assert cli.main(["extract", str(transcript_file)]) == 0

    assert written(transcript_file.parent) == ITEM_FILES
    out = capsys.readouterr().out
    assert "# Project Items" in out
    assert "## Needs PM Review" in out


def test_default_run_does_summary_and_extraction(mock_env, transcript_file):
    assert cli.main([str(transcript_file)]) == 0
    assert written(transcript_file.parent) == ALL_FILES


def test_default_transcript_is_transcript_md_in_current_folder(mock_env, transcript_file, monkeypatch):
    monkeypatch.chdir(transcript_file.parent)

    assert cli.main(["summarise"]) == 0
    assert cli.main([]) == 0
    assert written(transcript_file.parent) == ALL_FILES


def test_items_json_is_data_not_presentation(mock_env, transcript_file):
    cli.main(["extract", str(transcript_file)])

    document = json.loads((transcript_file.parent / "project_items.json").read_text(encoding="utf-8"))
    assert document["meetingSummary"].startswith("Extracted 6 project items")
    assert document["transcript"] == "transcript.md"
    assert document["meeting_date"] is None
    first = document["items"][0]
    assert first["record_id"] == "null-1"
    assert first["number"] == 1
    assert first["type"] == "Action"
    assert first["owner"] is None
    assert first["priority"] is None
    assert first["mitigation_next_step"] is None
    assert first["review_flag"] in {"Missing", "Ambiguous"}
    assert first["needs_pm_review"] is True
    assert first["source"] == {"speaker": "Kat", "quote": "We need to have the demo ready for Friday.",
                               "timestamp": None, "verified": True}
    assert "|" not in json.dumps(document)  # no Markdown table fragments in the data


def test_meeting_date_option_resolves_relative_dates(mock_env, transcript_file):
    cli.main(["extract", str(transcript_file), "--meeting-date", "2026-09-23"])

    document = json.loads((transcript_file.parent / "project_items.json").read_text(encoding="utf-8"))
    assert document["meeting_date"] == "2026-09-23"
    assert document["items"][0]["due_date"] == "2026-09-25"  # "Friday" after Wed 23rd
    assert document["items"][0]["due_date_text"] == "Friday"


def test_project_option_sets_project_and_record_ids(mock_env, transcript_file):
    cli.main(["extract", str(transcript_file), "--project", "AIBP"])

    document = json.loads((transcript_file.parent / "project_items.json").read_text(encoding="utf-8"))
    assert document["project"] == "AIBP"
    assert [item["record_id"] for item in document["items"]] == [f"AIBP-{i}" for i in range(1, 7)]
    assert all(item["project"] == "AIBP" for item in document["items"])


def test_meeting_date_is_read_from_transcript_header(mock_env, transcript_file):
    text = transcript_file.read_text(encoding="utf-8")
    transcript_file.write_text("Date: 2026-09-23\n\n" + text, encoding="utf-8")

    cli.main(["extract", str(transcript_file)])

    document = json.loads((transcript_file.parent / "project_items.json").read_text(encoding="utf-8"))
    assert document["meeting_date"] == "2026-09-23"


def test_bad_meeting_date_is_rejected_by_argument_parsing(mock_env, transcript_file, capsys):
    with pytest.raises(SystemExit):
        cli.main(["extract", str(transcript_file), "--meeting-date", "23/09/2026"])
    assert "not a date in YYYY-MM-DD form" in capsys.readouterr().err


def test_output_dir_option(mock_env, transcript_file, tmp_path):
    target = tmp_path / "out" / "meeting-1"

    assert cli.main(["all", str(transcript_file), "-o", str(target)]) == 0
    assert written(target) == ALL_FILES


def test_chat_command_runs_questions(mock_env, transcript_file, capsys):
    assert cli.main(["chat", str(transcript_file), "-q", "What did we decide about SharePoint?"]) == 0

    out = capsys.readouterr().out
    assert "Meeting loaded" in out
    assert "agreed to use SharePoint" in out


def test_chat_command_interactive(mock_env, transcript_file, capsys):
    lines = iter(["Who owns the Friday demo?", "exit"])

    assert cli.main(["chat", str(transcript_file)], read=lambda prompt: next(lines)) == 0
    assert "doesn't name an owner" in capsys.readouterr().out


# --- errors --------------------------------------------------------------------

def test_missing_transcript_fails_cleanly(mock_env, tmp_path, capsys):
    assert cli.main(["summarise", str(tmp_path / "transcript.md")]) == 1

    err = capsys.readouterr().err
    assert f"Error: Transcript file '{tmp_path / 'transcript.md'}' was not found." in err
    assert "Traceback" not in err


def test_empty_transcript_fails_cleanly(mock_env, tmp_path, capsys):
    path = tmp_path / "transcript.md"
    path.write_text("\n\n", encoding="utf-8")

    assert cli.main(["summarise", str(path)]) == 1
    assert capsys.readouterr().err.strip() == "Error: Transcript contains no usable text."


def test_missing_provider_setting_fails_cleanly(transcript_file, capsys):
    assert cli.main([str(transcript_file)]) == 1
    assert "Error: LLM_PROVIDER is not configured." in capsys.readouterr().err


def test_missing_azure_config_fails_cleanly(monkeypatch, transcript_file, capsys):
    monkeypatch.setenv("LLM_PROVIDER", "azure")

    assert cli.main([str(transcript_file)]) == 1
    assert "Error: AZURE_OPENAI_ENDPOINT is not configured." in capsys.readouterr().err
    assert written(transcript_file.parent) == []


def test_empty_summary_writes_nothing(use_provider, fake_provider, transcript_file, capsys):
    use_provider(fake_provider(reply=""))

    assert cli.main([str(transcript_file)]) == 1
    assert "empty summary" in capsys.readouterr().err
    assert written(transcript_file.parent) == []


def test_bad_extraction_reply_writes_nothing(use_provider, fake_provider, transcript_file, capsys):
    use_provider(fake_provider(items_reply="Sorry, no items."))

    assert cli.main([str(transcript_file)]) == 1
    assert "not valid JSON" in capsys.readouterr().err
    assert written(transcript_file.parent) == []


def test_provider_failure_fails_cleanly(use_provider, transcript_file, capsys):
    class FailingProvider:
        def generate(self, system_prompt, user_prompt):
            raise LLMProviderError("Could not reach Azure OpenAI.")

    use_provider(FailingProvider())

    assert cli.main(["summarise", str(transcript_file)]) == 1
    assert "Error: Could not reach Azure OpenAI." in capsys.readouterr().err
