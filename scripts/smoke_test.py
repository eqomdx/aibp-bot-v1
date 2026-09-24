"""Smoke-test a running AIBP Meeting Agent API, locally or through a Dev Tunnel.

    python scripts/smoke_test.py                                   # http://127.0.0.1:8000
    python scripts/smoke_test.py https://<id>-8000.<region>.devtunnels.ms

Checks /health, /docs, /openapi.json and one real POST /validate. Uses only the
standard library and sends no credentials. Exits 1 if any check fails.
"""

import json
import sys
import urllib.error
import urllib.request

TRANSCRIPT = "Kat: Annie, can you update the RAID log by Friday?\nAnnie: Yep, I'll do that."
PAYLOAD = {
    "transcript": TRANSCRIPT,
    "project": "AIBP",
    "meeting_date": "2026-09-24",
    "extraction": {"items": [{
        "type": "Action",
        "title": "Update RAID log",
        "description": "Update the RAID log.",
        "owner": "Annie",
        "due_date": "Friday",
        "confidence": "High",
        "source": {"speaker": "Annie", "quote": "Yep, I'll do that.", "timestamp": None},
    }]},
}


def request(base: str, path: str, body: dict | None = None) -> tuple[int, str, str]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(base + path, data=data, method="GET" if body is None else "POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "aibp-smoke-test"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, response.headers.get("Content-Type", ""), response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get("Content-Type", ""), error.read().decode("utf-8", "replace")


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
    print(f"Testing {base}\n")
    results = []

    def check(name: str, ok: bool, detail: str) -> None:
        results.append(ok)
        print(f"{'PASS' if ok else 'FAIL'}  {name:<22} {detail}")

    try:
        status, _, body = request(base, "/health")
        check("GET /health", status == 200 and json.loads(body) == {"status": "ok"}, f"{status} {body.strip()}")

        status, ctype, body = request(base, "/docs")
        check("GET /docs", status == 200 and "swagger" in body.lower(), f"{status} {ctype}")

        status, _, body = request(base, "/openapi.json")
        schema = json.loads(body) if status == 200 else {}
        ops = sorted(op.get("operationId", "?") for p in schema.get("paths", {}).values() for op in p.values())
        check("GET /openapi.json", status == 200 and "validateExtraction" in ops,
              f"{status} openapi {schema.get('openapi')} ops={ops}")

        status, _, body = request(base, "/validate", PAYLOAD)
        record = json.loads(body)["items"][0] if status == 200 else {}
        ok = (status == 200 and record.get("record_id") == "AIBP-1" and record.get("source", {}).get("verified") is True
              and record.get("due_date") == "2026-09-25")
        check("POST /validate", ok, f"{status} record_id={record.get('record_id')} "
              f"verified={record.get('source', {}).get('verified')} due_date={record.get('due_date')} "
              f"review_flag={record.get('review_flag')}")

        status, _, body = request(base, "/validate", {**PAYLOAD, "extraction": {"items": [{"type": "Task"}]}})
        check("POST /validate (bad)", status == 400, f"{status} {body.strip()[:90]}")
    except (urllib.error.URLError, OSError, ValueError) as error:
        check("connection", False, str(error))

    print(f"\n{sum(results)}/{len(results)} checks passed.")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
