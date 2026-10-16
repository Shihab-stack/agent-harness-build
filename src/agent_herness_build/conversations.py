"""Save and restore named conversation histories in the user workspace."""

import json
import re
from pathlib import Path
from typing import Any

from agent_herness_build.paths import WORKSPACE

CONVERSATION_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


def conversation_path(name: str) -> Path:
    """Return the safe path for a named conversation."""
    if not CONVERSATION_NAME.fullmatch(name):
        raise ValueError("name must be 1-64 letters, numbers, hyphens, or underscores")
    root = WORKSPACE.resolve()
    path = (root / "conversations" / f"{name}.json").resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("conversation path must stay inside the workspace") from exc
    return path


def save_conversation(name: str, messages: list[dict[str, Any]]) -> str:
    """Persist a conversation as UTF-8 JSON under the workspace."""
    path = conversation_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(messages, ensure_ascii=False, indent=2)
    path.write_text(content, encoding="utf-8")
    return f"saved conversation '{name}'"


def load_conversation(name: str) -> list[dict[str, Any]]:
    """Load a saved conversation and reject malformed history."""
    path = conversation_path(name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"no saved conversation named '{name}'") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"saved conversation '{name}' contains invalid JSON") from exc
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise ValueError(f"saved conversation '{name}' has an invalid format")
    return data
