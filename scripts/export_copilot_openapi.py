"""Export the API's OpenAPI schema as a Swagger 2.0 file for Copilot Studio.

    python scripts/export_copilot_openapi.py https://<id>-8000.<region>.devtunnels.ms
    python scripts/export_copilot_openapi.py https://... -o copilot/openapi.json

Why: FastAPI publishes OpenAPI 3.1. Copilot Studio REST API tools are built on
Power Platform, which needs OpenAPI v2 and a concrete host. This script derives
v2 from the app's own live schema (nothing is hand-maintained), so re-run it
whenever the API or the tunnel URL changes. The output contains your tunnel
host, so it is git-ignored; upload it in Copilot Studio.

Conversions (only the constructs this API uses):
- components/schemas -> definitions, $ref paths rewritten
- requestBody -> a single "body" parameter
- anyOf [X, null] -> X with x-nullable
- anyOf of several types (the `extraction` field) -> string, since Copilot
  passes the prompt's output as text and the API accepts raw JSON text
- `examples` (3.1) -> `example` (v2)
"""

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "copilot" / "openapi.json"


def to_swagger2(openapi: dict, base_url: str) -> dict:
    """Convert this app's OpenAPI 3.x schema to Swagger 2.0 for `base_url`."""
    url = urlparse(base_url)
    if url.scheme not in ("http", "https") or not url.netloc:
        raise ValueError(f"'{base_url}' is not an http(s) URL, e.g. https://abc123-8000.uks1.devtunnels.ms")

    spec = {
        "swagger": "2.0",
        "info": {key: openapi["info"][key] for key in ("title", "version", "description") if key in openapi["info"]},
        "host": url.netloc,
        "basePath": url.path.rstrip("/") or "/",
        "schemes": [url.scheme],
        "consumes": ["application/json"],
        "produces": ["application/json"],
        "paths": {},
        "definitions": {
            name: _schema(schema) for name, schema in openapi.get("components", {}).get("schemas", {}).items()
        },
    }

    for path, methods in openapi["paths"].items():
        spec["paths"][path] = {}
        for method, op in methods.items():
            converted = {key: op[key] for key in ("operationId", "summary", "description", "tags") if key in op}
            body = op.get("requestBody")
            if body:
                converted["parameters"] = [{
                    "in": "body",
                    "name": "body",
                    "required": body.get("required", False),
                    "schema": _schema(body["content"]["application/json"]["schema"]),
                }]
            converted["responses"] = {}
            for code, response in op.get("responses", {}).items():
                entry = {"description": response.get("description") or code}
                content = response.get("content", {}).get("application/json")
                if content and content.get("schema"):
                    entry["schema"] = _schema(content["schema"])
                converted["responses"][code] = entry
            spec["paths"][path][method] = converted
    return spec


def _schema(node):
    """Recursively rewrite a JSON Schema node from OpenAPI 3.1 to Swagger 2.0."""
    if isinstance(node, list):
        return [_schema(item) for item in node]
    if not isinstance(node, dict):
        return node

    node = dict(node)
    if "anyOf" in node:
        options = node.pop("anyOf")
        non_null = [option for option in options if option.get("type") != "null"]
        if len(non_null) == 1:
            node = {**_schema(non_null[0]), **node}
            if len(non_null) < len(options):
                node["x-nullable"] = True
        else:
            # v2 has no unions; the JSON-as-text form is accepted by the API and is what Copilot produces.
            node = {**node, "type": "string"}
            node["description"] = "Send as JSON text. " + node.get("description", "")

    if "examples" in node:
        examples = node.pop("examples")
        if isinstance(examples, list) and examples:
            node["example"] = examples[0]
    node.pop("const", None)

    if "$ref" in node:
        node["$ref"] = node["$ref"].replace("#/components/schemas/", "#/definitions/")
    for key in ("properties",):
        if key in node:
            node[key] = {name: _schema(value) for name, value in node[key].items()}
    for key in ("items", "additionalProperties"):
        if isinstance(node.get(key), dict):
            node[key] = _schema(node[key])
    return node


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a Swagger 2.0 spec of the API for Copilot Studio.")
    parser.add_argument("base_url", help="Public HTTPS base URL, e.g. https://abc123-8000.uks1.devtunnels.ms")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    from meeting_agent.api import app  # the live schema; no server needs to be running

    try:
        spec = to_swagger2(app.openapi(), args.base_url)
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote Swagger 2.0 spec for {spec['schemes'][0]}://{spec['host']} to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
