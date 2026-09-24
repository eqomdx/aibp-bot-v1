"""MCP interface onto the validation service, for Copilot Studio.

Exposes one tool, validate_meeting_extraction, over Streamable HTTP (the only
MCP transport Copilot Studio supports). The tool is a thin adapter: it calls
the same validation_service.validate_extraction() as REST POST /validate, so
both interfaces return identical records.

    REST POST /validate  ->  validation_service  <-  MCP validate_meeting_extraction

Like the REST API, this makes no model call, needs no credentials, reads no
.env and cannot write to any external system.

Tool schema notes, from Copilot Studio's documented MCP limitations: tools whose
input or output schema uses `$ref` are hidden, and a `type` listing several
types is truncated. So optional inputs are plain strings ("" means not given)
rather than `str | None`, and the output is a plain object.
"""

import logging
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import ToolAnnotations
from pydantic import Field
from starlette.applications import Starlette

from meeting_agent import __version__
from meeting_agent.errors import ExtractionError, MeetingAgentError, MeetingDateError, TranscriptError
from meeting_agent.validation_service import parse_meeting_date, validate_extraction

logger = logging.getLogger(__name__)

MCP_PATH = "/mcp"
TOOL_NAME = "validate_meeting_extraction"

SERVER_INSTRUCTIONS = """\
Governance layer for the AIBP project-management meeting agent. Call \
validate_meeting_extraction after extracting project items from a meeting \
transcript, and before showing them to a project manager. The tool does not \
extract items itself; it checks the extraction against the transcript.\
"""

TOOL_DESCRIPTION = """\
Validates AI-extracted project-management items against the original meeting transcript.
Verifies source evidence, removes duplicates, checks missing or inferred fields,
resolves dates when possible, assigns PM review flags, regenerates record IDs,
and returns structured RAID records.

Returns {"meetingSummary", "project", "meeting_date", "items": [...]}. Each item has
record_id, number, type, title, description, owner, due_date, status, review_flag
(None, Inferred, Missing or Ambiguous), needs_pm_review, review_reasons and
source (with verified true/false). Show items with needs_pm_review true to the PM
for checking. This tool validates an extraction; it does not create one.\
"""

mcp = MCPServer(
    name="aibp-meeting-agent",
    title="AIBP Meeting Agent",
    description="Validates AI-extracted meeting RAID items against the transcript.",
    instructions=SERVER_INSTRUCTIONS,
    version=__version__,
)


@mcp.tool(
    name=TOOL_NAME,
    title="Validate meeting extraction",
    description=TOOL_DESCRIPTION,
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
def validate_meeting_extraction(
    transcript: Annotated[str, Field(
        description="The original meeting transcript as plain text. Every item's quote, speaker and "
        "timestamp is checked against this.",
    )],
    extraction: Annotated[dict[str, Any], Field(
        description='The AI extraction to validate, as an object {"items": [...]}. Each item has type '
        "(Action, Decision, Risk, Issue, Dependency or Assumption), title, description, owner, due_date, "
        "confidence (High, Medium or Low) and source {speaker, quote, timestamp}.",
    )],
    project: Annotated[str, Field(
        description="Project name, applied to every item and used for record IDs such as AIBP-1. "
        "Leave empty if unknown.",
    )] = "",
    meeting_date: Annotated[str, Field(
        description="Meeting date as YYYY-MM-DD, used to resolve relative due dates such as 'Friday'. "
        "Leave empty if unknown; relative dates then stay unresolved and are flagged.",
    )] = "",
) -> dict[str, Any]:
    try:
        return validate_extraction(transcript, extraction, project, parse_meeting_date(meeting_date))
    except TranscriptError as exc:
        raise ToolError(f"invalid_transcript: {exc}") from None
    except MeetingDateError as exc:
        raise ToolError(f"invalid_meeting_date: {exc}") from None
    except ExtractionError as exc:
        raise ToolError(f"invalid_extraction: {exc}") from None
    except MeetingAgentError as exc:
        raise ToolError(f"invalid_request: {exc}") from None


def transport_security() -> TransportSecuritySettings:
    """DNS-rebinding protection that still admits requests forwarded by a Dev Tunnel.

    The API binds to localhost, and Dev Tunnels rewrite Host (and Origin) to
    "localhost" without a port, which the SDK's default allow-list rejects.
    """
    local = ["127.0.0.1", "localhost", "[::1]"]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[*local, *(f"{host}:*" for host in local)],
        allowed_origins=[f"{scheme}://{host}{port}" for scheme in ("http", "https") for host in local
                         for port in ("", ":*")],
    )


def build_mcp_app() -> Starlette:
    """A fresh Streamable HTTP app serving MCP at MCP_PATH.

    Build one per application start: its session manager can only run once.
    Stateless with JSON responses, so every request stands alone behind a proxy.
    """
    return mcp.streamable_http_app(
        streamable_http_path=MCP_PATH,
        stateless_http=True,
        json_response=True,
        transport_security=transport_security(),
    )
