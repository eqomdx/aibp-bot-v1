"""Writing results to disk."""

import json
from pathlib import Path

from meeting_agent.errors import OutputError


def save_markdown(path: str | Path, text: str) -> Path:
    """Write text to a UTF-8 Markdown file and return the path written."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text.rstrip() + "\n", encoding="utf-8")
    except OSError as exc:
        raise OutputError(f"Could not write {path}: {exc.strerror}") from None
    return path


def save_json(path: str | Path, data) -> Path:
    """Write data as indented UTF-8 JSON and return the path written."""
    return save_markdown(path, json.dumps(data, indent=2, ensure_ascii=False))
