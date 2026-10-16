"""Workspace file operations with path-traversal protection."""

from pathlib import Path

from agent_herness_build.paths import PROJECT_ROOT, WORKSPACE

PROJECT_READ_FILES = {"README.md", "pyproject.toml", "config/mcp_servers.example.json"}
PROJECT_READ_DIRECTORIES = {"src", "tests"}
PROJECT_LIST_DIRECTORIES = {*PROJECT_READ_DIRECTORIES, "config"}
PROJECT_DENIED_COMPONENTS = {
    "__pycache__",
    "build",
    "credentials",
    "dist",
    "node_modules",
    "secret",
    "secrets",
    "venv",
    "workspace",
}


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _is_sensitive_project_path(relative: str) -> bool:
    return any(
        part.startswith(".")
        or part.lower() in PROJECT_DENIED_COMPONENTS
        or part.lower() == "mcp_servers.json"
        or part.lower().startswith(("credentials.", ".env"))
        for part in Path(relative).parts
    )


def _project_read_path(filename: str) -> Path:
    if not isinstance(filename, str):
        raise ValueError("project path must be a string")
    requested = Path(filename)
    if requested.is_absolute() or ".." in requested.parts:
        raise ValueError("project path must be relative and may not contain '..'")
    root = PROJECT_ROOT.resolve()
    path = (root / requested).resolve()
    if not _is_relative_to(path, root):
        raise ValueError("project path must stay inside the project")

    relative = path.relative_to(root).as_posix()
    if _is_sensitive_project_path(relative):
        raise ValueError("project path is excluded from the read-only allowlist")
    allowed_file = relative in PROJECT_READ_FILES
    allowed_directory = relative == "config" or any(
        relative == directory or relative.startswith(f"{directory}/")
        for directory in PROJECT_READ_DIRECTORIES
    )
    if not allowed_file and not allowed_directory:
        raise ValueError("project path is not in the read-only project allowlist")
    return path


def _project_entry_is_allowed(path: Path) -> bool:
    try:
        resolved = path.resolve()
        root = PROJECT_ROOT.resolve()
        relative = resolved.relative_to(root).as_posix()
    except (OSError, RuntimeError, ValueError):
        return False
    if _is_sensitive_project_path(relative):
        return False
    return relative in PROJECT_READ_FILES or relative == "config" or any(
        relative == directory or relative.startswith(f"{directory}/")
        for directory in PROJECT_READ_DIRECTORIES
    )


def workspace_path(filename: str) -> Path:
    """Resolve a filename and reject paths that escape the user workspace."""
    root = WORKSPACE.resolve()
    path = (root / filename).resolve()
    if not _is_relative_to(path, root):
        raise ValueError("file must be inside the project workspace")
    return path


def generated_path(filename: str) -> Path:
    """Resolve a filename confined to workspace/generated."""
    if not isinstance(filename, str):
        raise ValueError("generated filename must be a string")
    requested = Path(filename)
    if not filename or requested.is_absolute() or ".." in requested.parts:
        raise ValueError("generated filename must be relative and may not contain '..'")
    workspace_root = WORKSPACE.resolve()
    generated_root = workspace_root / "generated"
    if generated_root.resolve() != generated_root:
        raise ValueError("generated directory must not be a symlink")
    path = (generated_root / requested).resolve()
    if not _is_relative_to(path, generated_root):
        raise ValueError("file must be inside workspace/generated")
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


def list_project_files(directory: str = ".") -> str:
    """List only explicitly allowlisted project files and directories."""
    if not isinstance(directory, str):
        return "error: project directory must be a string"
    if directory in {"", "."}:
        root = PROJECT_ROOT.resolve()
        candidates = ["README.md", "pyproject.toml", *PROJECT_LIST_DIRECTORIES]
        candidates.sort()
        entries = [
            relative
            for relative in candidates
            if (root / relative).exists() and _project_entry_is_allowed(root / relative)
        ]
        return "\n".join(entries) or "(empty)"
    try:
        path = _project_read_path(directory)
    except (OSError, RuntimeError, ValueError) as exc:
        return f"error: {exc}"
    if not path.is_dir():
        return f"error: no allowlisted project directory named {directory}"
    try:
        entries = [
            child.name
            for child in sorted(path.iterdir())
            if not child.name.startswith(".") and _project_entry_is_allowed(child)
        ]
    except OSError as exc:
        return f"error: could not list project directory {directory}: {exc}"
    return "\n".join(entries) or "(empty)"


def read_project_file(filename: str) -> str:
    """Read a text file only from the project inspection allowlist."""
    try:
        path = _project_read_path(filename)
    except (OSError, RuntimeError, ValueError) as exc:
        return f"error: {exc}"
    if not path.is_file():
        return f"error: no allowlisted project file named {filename}"
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return f"error: could not read project file {filename}: {exc}"


def write_file(filename: str, content: str) -> str:
    """Create or overwrite a text file under workspace/generated."""
    try:
        path = generated_path(filename)
    except (OSError, RuntimeError, ValueError) as exc:
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
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if generated_path(filename) != path:
            return "error: generated file path changed during write"
        path.write_text(content, encoding="utf-8")
    except (OSError, RuntimeError, ValueError) as exc:
        return f"error: could not write generated file {filename}: {exc}"
    return f"wrote generated/{filename}"


FILE_TOOLS = {
    "list_files": list_files,
    "read_file": read_file,
    "write_file": write_file,
    "list_project_files": list_project_files,
    "read_project_file": read_project_file,
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
            "name": "list_project_files",
            "description": (
                "List files in the read-only project inspection allowlist "
                "(README.md, pyproject.toml, src/, tests/, and the example MCP config)."
            ),
            "parameters": {
                "type": "object",
                "properties": {"directory": {"type": "string"}},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_project_file",
            "description": (
                "Read a text file from the read-only project allowlist. "
                "Project inspection only; credentials and local config are excluded."
            ),
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
                "Create a text file in workspace/generated/. Ask before overwriting "
                "an existing generated file. Project source files are read-only."
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
