import json

import pytest

from conftest import SAMPLE_TRANSCRIPT_PATH
from meeting_agent import main as cli
from meeting_agent.errors import LLMProviderError
from meeting_agent.meeting_service import MeetingService
from meeting_agent.providers.mock import MOCK_SUMMARY

OUTPUT_FILES = ("summary.md", "project_items.json", "project_items.md")


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    """Stop main() from loading the developer's real .env file."""
    monkeypatch.setattr(cli, "load_environment", lambda: None)


@pytest.fixture
def transcript_file(tmp_path):
    """A copy of the sample transcript, so the mock's sources verify."""
    path = tmp_path / "transcript.md"
    path.write_text(SAMPLE_TRANSCRIPT_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    return path


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")


@pytest.fixture
def use_provider(monkeypatch, mock_env):
    """Make the CLI build its MeetingService around the given provider."""

    def install(provider):
        monkeypatch.setattr(cli, "build_service", lambda name: MeetingService(provider))
        return provider

    return install


def written(folder):
    return [name for name in OUTPUT_FILES if (folder / name).exists()]


def test_full_flow_with_mock_provider(mock_env, transcript_file, capsys):
    """transcript.md -> MeetingService -> MockLLMProvider -> outputs, nothing patched."""
    exit_code = cli.main([str(transcript_file)])

    out = capsys.readouterr().out
    folder = transcript_file.parent
    assert exit_code == 0
    assert "with the 'mock' provider" in out
    assert written(folder) == list(OUTPUT_FILES)
    assert (folder / "summary.md").read_text(encoding="utf-8") == MOCK_SUMMARY
    assert MOCK_SUMMARY.strip() in out
    assert "# Project Items" in out
    assert "## Dependencies" in out


def test_items_json_is_machine_readable(mock_env, transcript_file):
    cli.main([str(transcript_file)])

    document = json.loads((transcript_file.parent / "project_items.json").read_text(encoding="utf-8"))

    assert document["transcript"] == "transcript.md"
    assert len(document["items"]) == 6
    first = document["items"][0]
    assert set(first) == {"type", "description", "owner", "due_date", "source", "confidence", "source_verified"}
    assert all(item["source_verified"] for item in document["items"])


def test_missing_information_is_saved_and_printed(mock_env, transcript_file, capsys):
    cli.main([str(transcript_file)])

    folder = transcript_file.parent
    document = json.loads((folder / "project_items.json").read_text(encoding="utf-8"))
    gaps = [(g["item_number"], g["gap"]) for g in document["missing_information"]]
    # Sample: demo action has no owner; Annie's and Izzy's actions have no due date;
    # the issue has no owner. The decision and Izzy's dependency are complete.
    assert gaps == [(1, "owner"), (2, "due_date"), (3, "due_date"), (5, "owner")]

    markdown = (folder / "project_items.md").read_text(encoding="utf-8")
    assert "## Missing Information" in markdown
    assert "- **Action: Have the demo ready.** No owner stated." in markdown
    assert "## Missing Information" in capsys.readouterr().out


def test_items_markdown_matches_terminal_output(mock_env, transcript_file, capsys):
    cli.main([str(transcript_file)])

    markdown = (transcript_file.parent / "project_items.md").read_text(encoding="utf-8")
    assert markdown in capsys.readouterr().out
    assert "| Annie |" in markdown


def test_transcript_reaches_both_requests(use_provider, fake_provider, transcript_file):
    provider = use_provider(fake_provider(reply="# Meeting Summary\n\n## Overview\nDemo prep."))

    assert cli.main([str(transcript_file)]) == 0
    assert len(provider.calls) == 2
    assert all("demo ready for Friday" in call["user_prompt"] for call in provider.calls)


def test_output_dir_option(mock_env, transcript_file, tmp_path):
    target = tmp_path / "out" / "meeting-1"

    assert cli.main([str(transcript_file), "-o", str(target)]) == 0
    assert written(target) == list(OUTPUT_FILES)


def test_defaults_to_transcript_md_in_current_folder(mock_env, transcript_file, monkeypatch):
    monkeypatch.chdir(transcript_file.parent)

    assert cli.main([]) == 0
    assert written(transcript_file.parent) == list(OUTPUT_FILES)


def test_missing_transcript_fails_cleanly(mock_env, tmp_path, capsys):
    exit_code = cli.main([str(tmp_path / "transcript.md")])

    err = capsys.readouterr().err
    assert exit_code == 1
    assert err.startswith("Error: Transcript file '")
    assert "was not found." in err
    assert "Traceback" not in err


def test_empty_transcript_fails_cleanly(mock_env, tmp_path, capsys):
    path = tmp_path / "transcript.md"
    path.write_text("\n\n", encoding="utf-8")

    assert cli.main([str(path)]) == 1
    assert capsys.readouterr().err.strip() == "Error: Transcript contains no usable text."


def test_missing_provider_setting_fails_cleanly(transcript_file, capsys):
    assert cli.main([str(transcript_file)]) == 1
    assert "Error: LLM_PROVIDER is not configured." in capsys.readouterr().err


def test_missing_azure_config_fails_cleanly(monkeypatch, transcript_file, capsys):
    monkeypatch.setenv("LLM_PROVIDER", "azure")

    exit_code = cli.main([str(transcript_file)])

    assert exit_code == 1
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

    assert cli.main([str(transcript_file)]) == 1
    assert "Error: Could not reach Azure OpenAI." in capsys.readouterr().err
