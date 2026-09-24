"""OpenAPI output for Copilot Studio: the live 3.1 schema and the exported Swagger 2.0 file."""

import importlib.util
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from meeting_agent.api import app

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_copilot_openapi.py"
BASE_URL = "https://abc123-8000.uks1.devtunnels.ms"


@pytest.fixture(scope="module")
def exporter():
    spec = importlib.util.spec_from_file_location("export_copilot_openapi", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def v2(exporter):
    return exporter.to_swagger2(app.openapi(), BASE_URL)


def walk(node):
    """Every dict inside a JSON structure."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def test_live_schema_does_not_document_422():
    """Bad requests return 400, so the schema must not promise 422."""
    schema = TestClient(app).get("/openapi.json").json()

    assert schema["openapi"].startswith("3.1")
    assert "422" not in schema["paths"]["/validate"]["post"]["responses"]
    assert "400" in schema["paths"]["/validate"]["post"]["responses"]
    assert "HTTPValidationError" not in schema["components"]["schemas"]


def test_export_is_swagger_2_with_the_given_host(v2):
    assert v2["swagger"] == "2.0"
    assert v2["host"] == "abc123-8000.uks1.devtunnels.ms"
    assert v2["schemes"] == ["https"]
    assert v2["basePath"] == "/"
    assert v2["info"]["title"] == "AIBP Meeting Agent API"


def test_export_keeps_operations_and_descriptions(v2):
    validate_op = v2["paths"]["/validate"]["post"]

    assert validate_op["operationId"] == "validateExtraction"
    assert "Validates AI-extracted project-management items" in validate_op["description"]
    assert v2["paths"]["/health"]["get"]["operationId"] == "health"
    assert validate_op["parameters"][0]["in"] == "body"
    assert validate_op["parameters"][0]["schema"] == {"$ref": "#/definitions/ValidateRequest"}
    assert set(validate_op["responses"]) == {"200", "400"}


def test_export_uses_no_openapi3_only_constructs(v2):
    for node in walk(v2):
        assert "anyOf" not in node and "oneOf" not in node and "examples" not in node
        assert node.get("type") != "null"
        if "$ref" in node:
            name = node["$ref"].removeprefix("#/definitions/")
            assert node["$ref"].startswith("#/definitions/") and name in v2["definitions"]


def test_optional_fields_become_nullable_strings(v2):
    project = v2["definitions"]["ValidateRequest"]["properties"]["project"]

    assert project["type"] == "string"
    assert project["x-nullable"] is True


def test_extraction_becomes_json_text(v2):
    extraction = v2["definitions"]["ValidateRequest"]["properties"]["extraction"]

    assert extraction["type"] == "string"
    assert extraction["description"].startswith("Send as JSON text.")


def test_json_text_extraction_really_is_accepted():
    """The v2 contract (extraction as a string) is one the live API honours."""
    from meeting_agent.api import EXAMPLE_ITEM_IN, EXAMPLE_ITEM_OUT, EXAMPLE_TRANSCRIPT

    response = TestClient(app).post("/validate", json={
        "transcript": EXAMPLE_TRANSCRIPT, "project": "AIBP", "meeting_date": "2026-09-24",
        "extraction": json.dumps({"items": [EXAMPLE_ITEM_IN]}),
    })

    assert response.status_code == 200
    assert response.json()["items"] == [EXAMPLE_ITEM_OUT]


@pytest.mark.parametrize("bad", ["abc123-8000.uks1.devtunnels.ms", "ftp://host", "https://"])
def test_bad_base_url_is_rejected(exporter, bad):
    with pytest.raises(ValueError, match="not an http"):
        exporter.to_swagger2(app.openapi(), bad)


def test_cli_writes_the_file(exporter, tmp_path):
    output = tmp_path / "openapi.json"

    assert exporter.main([BASE_URL, "-o", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["host"] == "abc123-8000.uks1.devtunnels.ms"


def test_exported_file_is_git_ignored():
    gitignore = (Path(__file__).resolve().parents[1] / ".gitignore").read_text(encoding="utf-8")

    assert "copilot/openapi.json" in gitignore
