import pytest

from conftest import SAMPLE_TRANSCRIPT_PATH
from meeting_agent import ask as cli
from meeting_agent.errors import LLMProviderError
from meeting_agent.meeting_service import MeetingService


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    """Stop main() from loading the developer's real .env file."""
    monkeypatch.setattr(cli, "load_environment", lambda: None)


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")


@pytest.fixture
def sample():
    return str(SAMPLE_TRANSCRIPT_PATH)


@pytest.fixture
def use_provider(monkeypatch, mock_env):
    def install(provider):
        monkeypatch.setattr(cli, "build_service", lambda name: MeetingService(provider))
        return provider

    return install


def scripted(*lines):
    """An input() replacement that returns each line, then signals end of input."""
    remaining = list(lines)

    def read(prompt):
        if not remaining:
            raise EOFError
        return remaining.pop(0)

    return read


# --- one-shot questions --------------------------------------------------

def test_single_question_with_mock(mock_env, sample, capsys):
    exit_code = cli.main([sample, "-q", "What did we decide about SharePoint?"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "with the 'mock' provider" in out
    assert "Q: What did we decide about SharePoint?" in out
    assert "agreed to use SharePoint" in out
    assert '"Yes, SharePoint makes sense for the first version. We can revisit Planner later."' in out
    assert "NOT FOUND" not in out


def test_brief_example_questions(mock_env, sample, capsys):
    exit_code = cli.main([
        sample,
        "-q", "What did we decide about SharePoint?",
        "-q", "Who owns the Friday demo?",
        "-q", "What unresolved risks were discussed?",
    ])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "does not name an owner" in out
    assert "No risks were explicitly discussed" in out
    assert "Warning" not in out


def test_follow_up_questions_carry_history(use_provider, fake_provider, sample):
    provider = use_provider(fake_provider())

    cli.main([sample, "-q", "When is the demo due?", "-q", "Who owns it?"])

    first, second = provider.calls
    assert "<earlier_conversation>" not in first["user_prompt"]
    assert "Q: When is the demo due?" in second["user_prompt"]


def test_failed_question_sets_exit_code_but_others_still_run(use_provider, sample, capsys):
    class FlakyProvider:
        def __init__(self):
            self.calls = 0

        def generate(self, system_prompt, user_prompt):
            self.calls += 1
            if self.calls == 1:
                raise LLMProviderError("Could not reach Azure OpenAI.")
            return '{"answer": "Friday.", "found_in_transcript": true, "sources": ["ready for Friday"]}'

    use_provider(FlakyProvider())

    exit_code = cli.main([sample, "-q", "First?", "-q", "When is the demo?"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Error: Could not reach Azure OpenAI." in captured.err
    assert "Friday." in captured.out


# --- interactive session -------------------------------------------------

def test_interactive_session_until_exit(mock_env, sample, capsys):
    read = scripted("", "What did we decide about SharePoint?", "exit", "never asked")

    assert cli.main([sample], read=read) == 0

    out = capsys.readouterr().out
    assert "Type 'exit' to stop." in out
    assert "agreed to use SharePoint" in out
    assert "never asked" not in out


@pytest.mark.parametrize("command", ["exit", "quit", "q", "EXIT"])
def test_exit_commands(mock_env, sample, command):
    assert cli.main([sample], read=scripted(command)) == 0


def test_end_of_input_ends_session(mock_env, sample):
    assert cli.main([sample], read=scripted()) == 0


def test_ctrl_c_ends_session_cleanly(mock_env, sample):
    def read(prompt):
        raise KeyboardInterrupt

    assert cli.main([sample], read=read) == 0


def test_error_does_not_end_interactive_session(use_provider, fake_provider, sample, capsys):
    use_provider(fake_provider(answer_reply="not json"))

    exit_code = cli.main([sample], read=scripted("Question one?", "Question two?"))

    err = capsys.readouterr().err
    assert exit_code == 0
    assert err.count("not valid JSON") == 2


def test_interactive_history_accumulates(use_provider, fake_provider, sample):
    provider = use_provider(fake_provider())

    cli.main([sample], read=scripted("A?", "B?", "C?"))

    assert "Q: A?" in provider.calls[2]["user_prompt"]
    assert "Q: B?" in provider.calls[2]["user_prompt"]


# --- startup errors ------------------------------------------------------

def test_missing_transcript(mock_env, tmp_path, capsys):
    assert cli.main([str(tmp_path / "transcript.md"), "-q", "Hi?"]) == 1
    assert "Error: Transcript file '" in capsys.readouterr().err


def test_missing_provider_setting(sample, capsys):
    assert cli.main([sample, "-q", "Hi?"]) == 1
    assert "Error: LLM_PROVIDER is not configured." in capsys.readouterr().err


def test_missing_azure_config(monkeypatch, sample, capsys):
    monkeypatch.setenv("LLM_PROVIDER", "azure")

    assert cli.main([sample, "-q", "Hi?"]) == 1
    assert "Error: AZURE_OPENAI_ENDPOINT is not configured." in capsys.readouterr().err
