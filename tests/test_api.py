"""Validation API (Copilot Studio integration): API01-API12 plus schema and safety checks.

No test here makes a network call or needs credentials.
"""

import json
import os
import socket
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from conftest import FAKE_API_KEY
from meeting_agent import api
from meeting_agent.api import EXAMPLE_ITEM_IN, EXAMPLE_ITEM_OUT, EXAMPLE_TRANSCRIPT, app

TRANSCRIPT = (
    "Kat: Annie, can you update the RAID log by Friday?\n"
    "Annie: Yep, I'll do that.\n"
    "Izzy: We've agreed to use SharePoint for the RAID log.\n"
    "Kat: Maybe Chloe could send the RAID document."
)


@pytest.fixture
def client():
    return TestClient(app)


def item(**overrides):
    return {**EXAMPLE_ITEM_IN, **overrides}


def decision(**overrides):
    return item(type="Decision", title="Use SharePoint", description="Use SharePoint for the RAID log.",
                owner=None, due_date=None,
                source={"speaker": "Izzy", "quote": "We've agreed to use SharePoint for the RAID log.",
                        "timestamp": None}, **overrides)


def payload(*items, transcript=TRANSCRIPT, project="AIBP", meeting_date="2026-09-24", **extra):
    body = {"transcript": transcript, "extraction": {"items": list(items)}, **extra}
    if project is not None:
        body["project"] = project
    if meeting_date is not None:
        body["meeting_date"] = meeting_date
    return body


def validate(client, body):
    response = client.post("/validate", json=body)
    return response, response.json()


# --- API01 -------------------------------------------------------------------

def test_api01_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --- API02 -------------------------------------------------------------------

def test_api02_successful_validation(client):
    response, body = validate(client, payload(item(), decision()))

    assert response.status_code == 200
    assert body["project"] == "AIBP"
    assert body["meeting_date"] == "2026-09-24"
    assert body["meetingSummary"].startswith("Extracted 2 project items")
    action, agreed = body["items"]
    assert (action["record_id"], action["number"]) == ("AIBP-1", 1)
    assert (agreed["record_id"], agreed["number"]) == ("AIBP-2", 2)
    assert action["project"] == agreed["project"] == "AIBP"
    assert action["meeting_date"] == "2026-09-24"
    assert action["source"]["verified"] is True
    assert action["due_date"] == "2026-09-25"
    assert action["review_flag"] == "None"
    assert action["needs_pm_review"] is False


def test_api02_documented_example_round_trips(client):
    """The example shown in /docs is exactly what the service returns."""
    response, body = validate(client, {"transcript": EXAMPLE_TRANSCRIPT, "project": "AIBP",
                                       "meeting_date": "2026-09-24", "extraction": {"items": [EXAMPLE_ITEM_IN]}})

    assert response.status_code == 200
    assert body["items"] == [EXAMPLE_ITEM_OUT]


# --- API03 -------------------------------------------------------------------

def test_api03_validate_needs_no_credentials_and_no_model(client, monkeypatch):
    """conftest has already removed every Azure/OpenAI variable. Any model path now explodes."""
    from meeting_agent.meeting_service import MeetingService
    from meeting_agent.providers import azure_openai, factory

    def forbidden(*args, **kwargs):
        raise AssertionError("/validate must not touch a provider, a model or the network")

    monkeypatch.setenv("LLM_PROVIDER", "azure")  # even when Azure is selected, /validate ignores it
    monkeypatch.setattr(azure_openai, "AzureOpenAI", forbidden)
    monkeypatch.setattr(factory, "create_provider", forbidden)
    monkeypatch.setattr(MeetingService, "extract_items", forbidden)
    real_connect = socket.socket.connect

    def local_only(sock, address, *args, **kwargs):
        # The in-process test client's event loop uses a loopback socket pair on Windows.
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            forbidden()
        return real_connect(sock, address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", local_only)

    for name in ("OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "CHAT_MODEL"):
        assert name not in os.environ

    response, body = validate(client, payload(item()))

    assert response.status_code == 200
    assert body["items"][0]["record_id"] == "AIBP-1"


def test_api03_api_module_never_loads_the_openai_sdk():
    """Architectural guarantee: the API's import graph contains no provider or SDK."""
    code = (
        "import sys, meeting_agent.api; "
        "bad = sorted(m for m in sys.modules if m == 'openai' or m.startswith(('openai.', 'meeting_agent.providers'))); "
        "print(bad)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)

    assert result.stdout.strip() == "[]"


# --- API04 -------------------------------------------------------------------

def test_api04_duplicates_become_one_record_and_ids_are_regenerated(client):
    response, body = validate(client, payload(item(), item(title="Update the RAID log again"), decision()))

    assert response.status_code == 200
    assert [i["type"] for i in body["items"]] == ["Action", "Decision"]
    assert [(i["number"], i["record_id"]) for i in body["items"]] == [(1, "AIBP-1"), (2, "AIBP-2")]


# --- API05 -------------------------------------------------------------------

def test_api05_fabricated_evidence_is_flagged(client):
    fabricated = item(source={"speaker": "Annie", "quote": "I'll have it done by noon Thursday.", "timestamp": None})

    response, body = validate(client, payload(fabricated))

    record = body["items"][0]
    assert response.status_code == 200
    assert record["source"]["verified"] is False
    assert record["review_flag"] == "Ambiguous"
    assert record["needs_pm_review"] is True
    assert "Source quote not found in the transcript." in record["review_reasons"]


def test_api05_fabricated_timestamp_is_flagged(client):
    response, body = validate(client, payload(item(source={"speaker": "Annie", "quote": "Yep, I'll do that.",
                                                           "timestamp": "10:42"})))

    assert body["items"][0]["source"]["verified"] is False
    assert body["items"][0]["review_flag"] == "Ambiguous"


# --- API06 -------------------------------------------------------------------

def test_api06_action_without_owner_is_flagged(client):
    response, body = validate(client, payload(item(owner=None)))

    record = body["items"][0]
    assert record["owner"] is None
    assert record["review_flag"] == "Missing"
    assert record["needs_pm_review"] is True
    assert "No owner stated." in record["review_reasons"]


def test_api06_decision_without_owner_is_fine(client):
    response, body = validate(client, payload(decision()))

    assert body["items"][0]["review_flag"] == "None"


# --- API07 -------------------------------------------------------------------

def test_api07_suggested_owner_is_inferred(client):
    suggested = item(title="Send RAID document", description="Send the RAID document.", owner="Chloe (suggested)",
                     due_date=None, source={"speaker": "Kat", "quote": "Maybe Chloe could send the RAID document.",
                                            "timestamp": None})

    response, body = validate(client, payload(suggested))

    record = body["items"][0]
    assert record["owner"] == "Chloe (suggested)"
    assert record["review_flag"] == "Inferred"
    assert record["needs_pm_review"] is True


def test_api07_higher_priority_flag_wins_over_inferred(client):
    suggested = item(owner="Chloe (suggested)", source={"speaker": "Kat", "quote": "Chloe promised it.", "timestamp": None})

    response, body = validate(client, payload(suggested))

    assert body["items"][0]["review_flag"] == "Ambiguous"


# --- API08 / API09 -----------------------------------------------------------

def test_api08_relative_date_resolves_with_meeting_date(client):
    response, body = validate(client, payload(item(due_date="Friday"), meeting_date="2026-09-24"))

    record = body["items"][0]
    assert record["due_date"] == "2026-09-25"  # Thursday 24th -> Friday 25th
    assert record["due_date_text"] == "Friday"
    assert record["review_flag"] == "None"


def test_api08_meeting_date_read_from_transcript_header(client):
    body = payload(item(), transcript="Date: 2026-09-24\n\n" + TRANSCRIPT, meeting_date=None)

    response, result = validate(client, body)

    assert result["meeting_date"] == "2026-09-24"
    assert result["items"][0]["due_date"] == "2026-09-25"


def test_api09_relative_date_without_meeting_date_stays_unresolved(client):
    response, body = validate(client, payload(item(due_date="Friday"), meeting_date=None))

    record = body["items"][0]
    assert response.status_code == 200
    assert body["meeting_date"] is None
    assert record["due_date"] is None
    assert record["due_date_text"] == "Friday"
    assert record["needs_pm_review"] is True
    assert record["review_flag"] != "None"
    assert any("meeting date is unknown" in reason for reason in record["review_reasons"])


# --- API10 - API12 and other errors -------------------------------------------

def test_api10_invalid_type_is_rejected(client):
    response, body = validate(client, payload(item(type="Task")))

    assert response.status_code == 400
    assert body["error"] == "invalid_extraction"
    assert "type 'Task'" in body["message"]
    assert "Action, Decision, Risk, Issue, Dependency, Assumption" in body["message"]


@pytest.mark.parametrize("transcript", ["", "   \n\t", "# Heading only\n"])
def test_api11_empty_transcript_is_rejected(client, transcript):
    response, body = validate(client, payload(item(), transcript=transcript))

    assert response.status_code == 400
    assert body == {"error": "invalid_transcript", "message": "Transcript contains no usable text."}


@pytest.mark.parametrize(
    ("extraction", "code", "message"),
    [
        ({"things": []}, "invalid_extraction", 'no "items" list'),
        ({"items": "not a list"}, "invalid_extraction", 'no "items" list'),
        ({"items": ["just text"]}, "invalid_extraction", "Item 1 is not a JSON object"),
        ({"items": [{"type": "Action"}]}, "invalid_extraction", "has no description"),
        ("this is not JSON", "invalid_extraction", "not valid JSON"),
        (42, "invalid_request", "extraction"),
    ],
)
def test_api12_malformed_extraction_is_rejected(client, extraction, code, message):
    response = client.post("/validate", json={"transcript": TRANSCRIPT, "extraction": extraction})

    assert response.status_code == 400
    assert response.json()["error"] == code
    assert message in response.json()["message"]


def test_missing_fields_are_rejected_with_400(client):
    response = client.post("/validate", json={"transcript": TRANSCRIPT})

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"
    assert "extraction" in response.json()["message"]


def test_non_json_body_is_rejected_with_400(client):
    response = client.post("/validate", content="not json", headers={"content-type": "application/json"})

    assert response.status_code == 400


@pytest.mark.parametrize("bad_date", ["24/09/2026", "2026-02-30", "tomorrow"])
def test_invalid_meeting_date_is_rejected(client, bad_date):
    response, body = validate(client, payload(item(), meeting_date=bad_date))

    assert response.status_code == 400
    assert body["error"] == "invalid_meeting_date"


def test_extraction_as_raw_model_text_is_accepted(client):
    """Copilot prompts return text; a fenced JSON reply can be passed straight through."""
    raw = "```json\n" + json.dumps({"items": [item()]}) + "\n```"

    response, body = validate(client, {"transcript": TRANSCRIPT, "extraction": raw, "project": "AIBP",
                                       "meeting_date": "2026-09-24"})

    assert response.status_code == 200
    assert body["items"][0]["record_id"] == "AIBP-1"


def test_bare_list_extraction_is_accepted(client):
    response = client.post("/validate", json={"transcript": TRANSCRIPT, "extraction": [item()], "project": "AIBP"})

    assert response.status_code == 200


def test_missing_project_is_flagged_not_rejected(client):
    response, body = validate(client, payload(item(), project=None))

    assert response.status_code == 200
    assert body["items"][0]["record_id"] == "null-1"
    assert "Project is missing." in body["items"][0]["review_reasons"]


# --- no leaks ---------------------------------------------------------------

def test_unexpected_errors_return_500_without_internals(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError(f"internal detail {FAKE_API_KEY}")

    monkeypatch.setattr(api, "validate_extraction", boom)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/validate", json=payload(item()))

    assert response.status_code == 500
    assert response.json()["error"] == "internal_error"
    assert FAKE_API_KEY not in response.text
    assert "Traceback" not in response.text
    assert "RuntimeError" not in response.text


def test_responses_never_contain_environment_values(client, azure_env):
    responses = [
        client.get("/health").text,
        client.post("/validate", json=payload(item())).text,
        client.post("/validate", json=payload(item(type="Task"))).text,
        client.post("/validate", json={"transcript": ""}).text,
    ]

    for value in azure_env.values():
        assert all(value not in text for text in responses)


# --- OpenAPI (for import into Copilot Studio as a REST API tool) --------------

def test_openapi_schema_is_published(client):
    schema = client.get("/openapi.json").json()

    assert schema["info"]["title"] == "AIBP Meeting Agent API"
    validate_op = schema["paths"]["/validate"]["post"]
    assert validate_op["operationId"] == "validateExtraction"
    assert "Validates AI-extracted project-management items against the original meeting" in validate_op["description"]
    assert "400" in validate_op["responses"]
    assert schema["paths"]["/health"]["get"]["operationId"] == "health"


def test_docs_page_is_served(client):
    assert client.get("/docs").status_code == 200
