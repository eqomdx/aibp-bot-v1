"""MCP interface (Copilot Studio): MCP01-MCP10 plus protocol, schema and safety checks.

Tests talk JSON-RPC to the real /mcp endpoint of the FastAPI app, in process.
No test makes a network call or needs credentials.
"""

import json
import os
import socket
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from conftest import FAKE_API_KEY
from meeting_agent import mcp_server
from meeting_agent.api import EXAMPLE_ITEM_IN, EXAMPLE_ITEM_OUT, EXAMPLE_TRANSCRIPT, app
from meeting_agent.mcp_server import TOOL_NAME

TRANSCRIPT = (
    "Kat: Annie, can you update the RAID log by Friday?\n"
    "Annie: Yep, I'll do that.\n"
    "Izzy: We've agreed to use SharePoint for the RAID log.\n"
    "Kat: Maybe Chloe could send the RAID document."
)
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
# The SDK prefixes every tool error with this; the service's own message follows it.
ERROR_PREFIX = f"Error executing tool {TOOL_NAME}: "


@pytest.fixture
def client():
    # The `with` block runs the app's lifespan, which starts the MCP session manager.
    with TestClient(app, base_url="http://localhost:8000") as test_client:
        yield test_client


def rpc(client, method, params=None, headers=None):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    response = client.post("/mcp", headers={**HEADERS, **(headers or {})}, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def call(client, **arguments):
    """Call the tool and return (is_error, structured result or error text)."""
    result = rpc(client, "tools/call", {"name": TOOL_NAME, "arguments": arguments})["result"]
    if result.get("isError"):
        return True, result["content"][0]["text"]
    return False, result["structuredContent"]


def item(**overrides):
    return {**EXAMPLE_ITEM_IN, **overrides}


def arguments(*items, transcript=TRANSCRIPT, project="AIBP", meeting_date="2026-09-24"):
    return {"transcript": transcript, "extraction": {"items": list(items)}, "project": project,
            "meeting_date": meeting_date}


# --- protocol ----------------------------------------------------------------

def test_initialize_handshake(client):
    result = rpc(client, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                        "clientInfo": {"name": "test", "version": "0"}})["result"]

    assert result["protocolVersion"] == "2025-06-18"
    assert result["serverInfo"]["name"] == "aibp-meeting-agent"
    assert "tools" in result["capabilities"]
    assert "validate_meeting_extraction" in result["instructions"]


@pytest.mark.parametrize("version", ["2024-11-05", "2025-03-26", "2025-11-25"])
def test_older_protocol_versions_are_accepted(client, version):
    result = rpc(client, "initialize", {"protocolVersion": version, "capabilities": {},
                                        "clientInfo": {"name": "test", "version": "0"}})["result"]

    assert result["protocolVersion"] == version


# --- MCP01 ---------------------------------------------------------------------

def test_mcp01_tool_is_listed_with_described_inputs(client):
    tools = rpc(client, "tools/list")["result"]["tools"]

    assert [tool["name"] for tool in tools] == ["validate_meeting_extraction"]
    tool = tools[0]
    assert tool["description"].startswith(
        "Validates AI-extracted project-management items against the original meeting transcript.")
    assert tool["annotations"]["readOnlyHint"] is True
    schema = tool["inputSchema"]
    assert schema["required"] == ["transcript", "extraction"]
    assert set(schema["properties"]) == {"transcript", "extraction", "project", "meeting_date"}
    assert all(prop["description"] for prop in schema["properties"].values())
    assert schema["properties"]["extraction"]["type"] == "object"


def test_mcp01_schemas_avoid_constructs_copilot_studio_rejects(client):
    """Copilot Studio hides tools with $ref and truncates multi-type `type` fields."""
    tool = rpc(client, "tools/list")["result"]["tools"][0]

    for schema in (tool["inputSchema"], tool["outputSchema"]):
        text = json.dumps(schema)
        assert "$ref" not in text and "$defs" not in text
        assert "anyOf" not in text and "oneOf" not in text
        for node in [schema, *schema.get("properties", {}).values()]:
            assert isinstance(node.get("type", ""), str)


# --- MCP02 ---------------------------------------------------------------------

def test_mcp02_valid_extraction_returns_raid_records(client):
    is_error, result = call(client, **arguments(item()))

    assert not is_error
    assert result["project"] == "AIBP"
    assert result["meeting_date"] == "2026-09-24"
    assert result["meetingSummary"].startswith("Extracted 1 project items")
    record = result["items"][0]
    assert (record["record_id"], record["number"], record["type"]) == ("AIBP-1", 1, "Action")
    assert record["source"]["verified"] is True
    assert (record["review_flag"], record["needs_pm_review"]) == ("None", False)


def test_mcp02_text_content_carries_the_same_json(client):
    """Clients that read only text content still get the full result."""
    result = rpc(client, "tools/call", {"name": TOOL_NAME, "arguments": arguments(item())})["result"]

    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]


def test_mcp02_optional_inputs_may_be_omitted(client):
    is_error, result = call(client, transcript=TRANSCRIPT, extraction={"items": [item()]})

    assert not is_error
    assert result["project"] is None and result["meeting_date"] is None
    assert result["items"][0]["record_id"] == "null-1"


# --- MCP03 ---------------------------------------------------------------------

def test_mcp03_no_credentials_model_or_network_needed(client, monkeypatch):
    from meeting_agent.meeting_service import MeetingService
    from meeting_agent.providers import azure_openai, factory

    def forbidden(*args, **kwargs):
        raise AssertionError("the MCP tool must not touch a provider, a model or the network")

    real_connect = socket.socket.connect

    def local_only(sock, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):  # the test client's event loop uses loopback
            forbidden()
        return real_connect(sock, address, *args, **kwargs)

    monkeypatch.setenv("LLM_PROVIDER", "azure")
    monkeypatch.setattr(azure_openai, "AzureOpenAI", forbidden)
    monkeypatch.setattr(factory, "create_provider", forbidden)
    monkeypatch.setattr(MeetingService, "extract_items", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", local_only)
    for name in ("OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "CHAT_MODEL"):
        assert name not in os.environ

    is_error, result = call(client, **arguments(item()))

    assert not is_error
    assert result["items"][0]["record_id"] == "AIBP-1"


def test_mcp03_mcp_module_never_loads_the_openai_sdk():
    code = (
        "import sys, meeting_agent.mcp_server, meeting_agent.api; "
        "print(sorted(m for m in sys.modules if m == 'openai' or m.startswith(('openai.', 'meeting_agent.providers'))))"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)

    assert result.stdout.strip() == "[]"


# --- MCP04 - MCP08 --------------------------------------------------------------

def decision():
    return item(type="Decision", title="Use SharePoint", description="Use SharePoint for the RAID log.",
                owner=None, due_date=None,
                source={"speaker": "Izzy", "quote": "We've agreed to use SharePoint for the RAID log.",
                        "timestamp": None})


def test_mcp04_duplicates_removed_and_ids_regenerated(client):
    is_error, result = call(client, **arguments(item(), item(title="Update the RAID log again"), decision()))

    assert [(r["number"], r["record_id"], r["type"]) for r in result["items"]] == [
        (1, "AIBP-1", "Action"), (2, "AIBP-2", "Decision")]


def test_mcp05_fabricated_quote_is_flagged(client):
    fabricated = item(source={"speaker": "Annie", "quote": "I'll have it done by noon Thursday.", "timestamp": None})

    is_error, result = call(client, **arguments(fabricated))

    record = result["items"][0]
    assert record["source"]["verified"] is False
    assert record["review_flag"] == "Ambiguous"
    assert record["needs_pm_review"] is True


def test_mcp06_missing_action_owner_is_flagged(client):
    is_error, result = call(client, **arguments(item(owner=None)))

    record = result["items"][0]
    assert record["review_flag"] == "Missing"
    assert record["needs_pm_review"] is True
    assert "No owner stated." in record["review_reasons"]


def test_mcp07_suggested_owner_is_inferred(client):
    suggested = item(title="Send RAID document", description="Send the RAID document.", owner="Chloe (suggested)",
                     due_date=None, source={"speaker": "Kat", "quote": "Maybe Chloe could send the RAID document.",
                                            "timestamp": None})

    is_error, result = call(client, **arguments(suggested))

    assert result["items"][0]["review_flag"] == "Inferred"
    assert result["items"][0]["needs_pm_review"] is True


def test_mcp08_relative_date_resolves_with_meeting_date(client):
    is_error, result = call(client, **arguments(item(due_date="Friday"), meeting_date="2026-09-24"))

    assert result["items"][0]["due_date"] == "2026-09-25"
    assert result["items"][0]["due_date_text"] == "Friday"


def test_mcp08_relative_date_without_meeting_date_is_not_invented(client):
    is_error, result = call(client, **arguments(item(due_date="Friday"), meeting_date=""))

    assert result["items"][0]["due_date"] is None
    assert result["items"][0]["needs_pm_review"] is True


# --- MCP09 and other errors ------------------------------------------------------

def test_mcp09_invalid_type_is_rejected(client):
    is_error, message = call(client, **arguments(item(type="Task")))

    assert is_error
    assert message.startswith(ERROR_PREFIX + "invalid_extraction: Item 1 has type 'Task'.")
    assert "Action, Decision, Risk, Issue, Dependency, Assumption" in message


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ({"transcript": "   ", "extraction": {"items": []}}, "invalid_transcript: Transcript contains no usable text."),
        ({"transcript": TRANSCRIPT, "extraction": {"things": []}}, 'invalid_extraction: The model reply has no "items" list.'),
        ({"transcript": TRANSCRIPT, "extraction": {"items": ["text"]}}, "invalid_extraction: Item 1 is not a JSON object."),
        ({"transcript": TRANSCRIPT, "extraction": {"items": []}, "meeting_date": "24/09/2026"},
         "invalid_meeting_date: meeting_date '24/09/2026' is not a valid date in YYYY-MM-DD form."),
    ],
    ids=["empty-transcript", "missing-items", "malformed-item", "bad-date"],
)
def test_useful_errors(client, args, expected):
    is_error, message = call(client, **args)

    assert is_error
    assert message == ERROR_PREFIX + expected


def test_wrong_argument_types_are_rejected(client):
    is_error, message = call(client, transcript=TRANSCRIPT, extraction="not an object")

    assert is_error
    assert "extraction" in message


def test_unexpected_errors_reveal_nothing(client, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError(f"internal detail {FAKE_API_KEY}")

    monkeypatch.setattr(mcp_server, "validate_extraction", boom)

    is_error, message = call(client, **arguments(item()))

    assert is_error
    assert message == f"Error executing tool {TOOL_NAME}"
    assert FAKE_API_KEY not in message and "Traceback" not in message


# --- MCP10 ---------------------------------------------------------------------

@pytest.mark.parametrize("scenario", ["valid", "duplicate", "fabricated", "no-owner", "suggested", "no-date"])
def test_mcp10_rest_and_mcp_return_identical_results(client, scenario):
    extraction_items = {
        "valid": [item()],
        "duplicate": [item(), item(), decision()],
        "fabricated": [item(source={"speaker": "Annie", "quote": "Invented.", "timestamp": None})],
        "no-owner": [item(owner=None)],
        "suggested": [item(owner="Chloe (suggested)")],
        "no-date": [item(due_date="Friday")],
    }[scenario]
    meeting_date = "" if scenario == "no-date" else "2026-09-24"

    rest = client.post("/validate", json={"transcript": TRANSCRIPT, "extraction": {"items": extraction_items},
                                          "project": "AIBP", "meeting_date": meeting_date or None})
    is_error, mcp_result = call(client, **arguments(*extraction_items, meeting_date=meeting_date))

    assert rest.status_code == 200 and not is_error
    assert mcp_result == rest.json()


def test_mcp10_rest_validate_unchanged(client):
    response = client.post("/validate", json={"transcript": EXAMPLE_TRANSCRIPT, "project": "AIBP",
                                              "meeting_date": "2026-09-24", "extraction": {"items": [EXAMPLE_ITEM_IN]}})

    assert response.status_code == 200
    assert response.json()["items"] == [EXAMPLE_ITEM_OUT]
    assert client.get("/health").json() == {"status": "ok"}


def test_mcp10_rest_error_codes_unchanged(client):
    response = client.post("/validate", json={"transcript": TRANSCRIPT, "extraction": {"items": []},
                                              "meeting_date": "24/09/2026"})

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_meeting_date",
                               "message": "meeting_date '24/09/2026' is not a valid date in YYYY-MM-DD form."}


# --- transport security and availability -------------------------------------

@pytest.mark.parametrize("host", ["localhost", "localhost:8000", "127.0.0.1:8000"])
def test_local_and_tunnel_host_headers_are_accepted(client, host):
    """Dev Tunnels forward requests with Host rewritten to plain 'localhost'."""
    result = rpc(client, "tools/list", headers={"Host": host})

    assert result["result"]["tools"]


def test_foreign_host_header_is_rejected(client):
    response = client.post("/mcp", headers={**HEADERS, "Host": "evil.example.com"},
                           json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})

    assert response.status_code == 421


def test_foreign_origin_is_rejected(client):
    response = client.post("/mcp", headers={**HEADERS, "Origin": "https://evil.example.com"},
                           json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})

    assert response.status_code == 403


def test_mcp_is_not_in_the_rest_openapi_schema(client):
    assert "/mcp" not in client.get("/openapi.json").json()["paths"]


def test_mcp_unavailable_without_app_startup():
    response = TestClient(app).post("/mcp", headers=HEADERS, json={})

    assert response.status_code == 503
    assert response.json()["error"] == "mcp_unavailable"


def test_app_can_start_repeatedly():
    """Each start builds a fresh MCP session manager (a manager can only run once)."""
    for _ in range(2):
        with TestClient(app, base_url="http://localhost:8000") as test_client:
            assert rpc(test_client, "tools/list")["result"]["tools"]
