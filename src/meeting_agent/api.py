"""HTTP API for the meeting agent's validation (governance) layer.

    uvicorn meeting_agent.api:app --reload

A thin interface over validation_service: it checks the request shape, parses
the meeting date and maps errors to HTTP responses. All domain logic lives in
the existing modules. The API needs no credentials, reads no .env file, never
calls a model and cannot write to any external system.
"""

import logging
from datetime import date
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from meeting_agent import __version__
from meeting_agent.errors import ExtractionError, MeetingAgentError, TranscriptError
from meeting_agent.validation_service import validate_extraction

logger = logging.getLogger(__name__)

MAX_TRANSCRIPT_CHARS = 1_000_000

API_DESCRIPTION = """\
Governance layer for the AIBP project-management meeting agent.

An AI model (for example in Copilot Studio) proposes Actions, Decisions, Risks,
Issues, Dependencies and Assumptions from a meeting transcript. This service does
not trust that output: it checks every item against the original transcript with
deterministic rules and returns structured RAID records for PM review.

The service makes no model calls, needs no API keys, and never writes to
SharePoint, Planner, email or Teams. Those downstream actions happen only after
a project manager has reviewed and approved the records.
"""

VALIDATE_DESCRIPTION = """\
Validates AI-extracted project-management items against the original meeting
transcript, verifies source evidence, removes duplicates, flags ambiguity or
missing information, and returns structured RAID records for PM review.

Steps, all deterministic:
1. Parse the extraction and reject anything outside the schema (for example an
   item type other than Action, Decision, Risk, Issue, Dependency or Assumption).
2. Remove duplicate items.
3. Verify each item's quote, speaker and timestamp against the transcript.
4. Resolve relative due dates ("Friday", "tomorrow") only when the meeting date is known.
5. Renumber items sequentially and regenerate record IDs as `<project>-<number>`.
6. Set `review_flag` (None, Inferred, Missing or Ambiguous) and `needs_pm_review`,
   with human-readable `review_reasons`.

`meeting_date` is optional; without it, a `Date: YYYY-MM-DD` line at the top of
the transcript is used if present. Without any meeting date, relative due dates
stay unresolved and are flagged for review.
"""

EXAMPLE_TRANSCRIPT = "Kat: Annie, can you update the RAID log by Friday?\nAnnie: Yep, I'll do that."

EXAMPLE_ITEM_IN = {
    "type": "Action",
    "title": "Update RAID log",
    "description": "Update the RAID log.",
    "owner": "Annie",
    "due_date": "Friday",
    "status": "Open",
    "priority": None,
    "impact": None,
    "likelihood": None,
    "mitigation_next_step": None,
    "decision_rationale": None,
    "source": {"speaker": "Annie", "quote": "Yep, I'll do that.", "timestamp": None},
    "confidence": "High",
    "review_flag": "None",
    "needs_pm_review": False,
    "review_reason": None,
    "reviewer_notes": None,
}

EXAMPLE_ITEM_OUT = {
    "record_id": "AIBP-1",
    "number": 1,
    "project": "AIBP",
    "meeting_date": "2026-09-24",
    "type": "Action",
    "title": "Update RAID log",
    "description": "Update the RAID log.",
    "owner": "Annie",
    "due_date": "2026-09-25",
    "status": "Open",
    "priority": None,
    "impact": None,
    "likelihood": None,
    "mitigation_next_step": None,
    "decision_rationale": None,
    "source_evidence": 'Annie: "Yep, I\'ll do that."',
    "review_flag": "None",
    "reviewer_notes": None,
    "due_date_text": "Friday",
    "source": {"speaker": "Annie", "quote": "Yep, I'll do that.", "timestamp": None, "verified": True},
    "confidence": "High",
    "needs_pm_review": False,
    "review_reasons": [],
}


class ValidateRequest(BaseModel):
    """A transcript plus the extraction an AI model produced from it."""

    transcript: str = Field(
        max_length=MAX_TRANSCRIPT_CHARS,
        description="The original meeting transcript, as plain text. Evidence is checked against this.",
    )
    extraction: dict[str, Any] | list[Any] | str = Field(
        description='The AI extraction: an object {"items": [...]}, a bare list of items, or the '
        "model's raw JSON text. The item schema is enforced by the service, not here.",
    )
    project: str | None = Field(
        default=None, description="Project name. Applied to every item and used for record IDs."
    )
    meeting_date: str | None = Field(
        default=None,
        description="Meeting date as YYYY-MM-DD. Used to resolve relative due dates such as 'Friday'.",
    )

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "transcript": EXAMPLE_TRANSCRIPT,
        "project": "AIBP",
        "meeting_date": "2026-09-24",
        "extraction": {"items": [EXAMPLE_ITEM_IN]},
    }]})


class ValidateResponse(BaseModel):
    """Validated RAID records, ready for PM review."""

    meetingSummary: str = Field(description="One-paragraph summary of what was extracted and how much needs review.")
    project: str | None = Field(description="The project applied to the items, if given.")
    meeting_date: str | None = Field(description="The meeting date used (YYYY-MM-DD), if known.")
    items: list[dict[str, Any]] = Field(
        description="Validated records in the RAID schema: record_id, number, project, meeting_date, type, "
        "title, description, owner, due_date (resolved, YYYY-MM-DD or null), status, priority, impact, "
        "likelihood, mitigation_next_step, decision_rationale, source_evidence, review_flag, reviewer_notes, "
        "plus due_date_text, source (with verified), confidence, needs_pm_review and review_reasons.",
    )

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "meetingSummary": "Extracted 1 project items (1 Action) covering Update RAID log. "
                          "0 have an outstanding Review Flag.",
        "project": "AIBP",
        "meeting_date": "2026-09-24",
        "items": [EXAMPLE_ITEM_OUT],
    }]})


class HealthResponse(BaseModel):
    status: str = Field(description='Always "ok" when the service is running.')


class ErrorResponse(BaseModel):
    error: str = Field(description="Machine-readable error code.")
    message: str = Field(description="Human-readable explanation.")


app = FastAPI(
    title="AIBP Meeting Agent API",
    version=__version__,
    description=API_DESCRIPTION,
)


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "message": message})


@app.exception_handler(RequestValidationError)
async def _bad_request(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Report malformed requests as 400 with field names, without echoing the submitted data."""
    problems = "; ".join(
        f"{'.'.join(str(part) for part in err.get('loc', ()) if part != 'body') or 'body'}: {err.get('msg')}"
        for err in exc.errors()
    )
    return _error(400, "invalid_request", f"The request is not valid: {problems}")


@app.exception_handler(Exception)
async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
    """Never return a stack trace or internal details to the caller."""
    logger.exception("Unhandled error in %s %s", request.method, request.url.path)
    return _error(500, "internal_error", "The service hit an unexpected error. No result was produced.")


@app.get(
    "/health",
    operation_id="health",
    summary="Health check",
    description="Returns {\"status\": \"ok\"} when the service is running. Makes no model call and needs no credentials.",
    response_model=HealthResponse,
    tags=["service"],
)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post(
    "/validate",
    operation_id="validateExtraction",
    summary="Validate AI-extracted meeting items against the transcript",
    description=VALIDATE_DESCRIPTION,
    response_model=ValidateResponse,
    responses={400: {"model": ErrorResponse, "description": "Invalid transcript, extraction or meeting date."}},
    tags=["validation"],
)
def validate(request: ValidateRequest):
    raw_date = (request.meeting_date or "").strip()
    try:
        meeting_date = date.fromisoformat(raw_date) if raw_date else None
    except ValueError:
        return _error(400, "invalid_meeting_date",
                      f"meeting_date '{request.meeting_date}' is not a valid date in YYYY-MM-DD form.")

    try:
        result = validate_extraction(request.transcript, request.extraction, request.project, meeting_date)
    except TranscriptError as exc:
        return _error(400, "invalid_transcript", str(exc))
    except ExtractionError as exc:
        return _error(400, "invalid_extraction", str(exc))
    except MeetingAgentError as exc:
        return _error(400, "invalid_request", str(exc))
    return ValidateResponse(**result)
