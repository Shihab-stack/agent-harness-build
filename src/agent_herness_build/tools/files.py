"""Workspace file operations with path-traversal protection."""

from pathlib import Path

from agent_herness_build.paths import WORKSPACE


def workspace_path(filename: str) -> Path:
    """Resolve a filename and reject paths that escape the user workspace."""
    root = WORKSPACE.resolve()
    path = (root / filename).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("file must be inside the project workspace") from exc
    return path


def list_files() -> str:
    """List entries in the workspace, creating it on first use."""
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    return "\n".join(path.name for path in sorted(WORKSPACE.iterdir())) or "(empty)"


def read_file(filename: str) -> str:
    """Read a text file from the workspace and report missing files clearly."""
    try:
        path = workspace_path(filename)
    except ValueError as exc:
        return f"error: {exc}"
    if not path.is_file():
        return f"error: no file named {filename}"
    return path.read_text(encoding="utf-8")


def write_file(filename: str, content: str) -> str:
    """Create or overwrite a text file without leaving the workspace."""
    try:
        path = workspace_path(filename)
    except ValueError as exc:
        return f"error: {exc}"
    if path.exists():
        try:
            answer = input(
                f"{filename} already exists. Overwrite it? [y/N] "
            ).strip().lower()
        except EOFError:
            return f"cancelled: kept existing file {filename}"
        if answer not in {"y", "yes"}:
            return f"cancelled: kept existing file {filename}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"wrote {filename}"


FILE_TOOLS = {
    "list_files": list_files,
    "read_file": read_file,
    "write_file": write_file,
}

FILE_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files in the user's workspace.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file from the user's workspace.",
            "parameters": {
                "type": "object",
                "properties": {"filename": {"type": "string"}},
                "required": ["filename"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Create a text file in the user's workspace. Ask before overwriting "
                "an existing file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["filename", "content"],
                "additionalProperties": False,
            },
        },
    },
]
