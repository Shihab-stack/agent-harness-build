"""Shared paths for project configuration and persistent local user data."""

import os
from pathlib import Path


def find_project_root() -> Path:
    """Find the checkout root, honoring an explicit path for installed use."""
    configured_root = os.environ.get("AGENT_PROJECT_ROOT")
    if configured_root:
        return Path(configured_root).expanduser().resolve()
    for candidate in (Path.cwd(), *Path.cwd().parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return Path.cwd().resolve()


PROJECT_ROOT = find_project_root()
WORKSPACE = Path(os.environ.get("AGENT_WORKSPACE", PROJECT_ROOT / "workspace")).expanduser()
CONFIG_DIR = Path(os.environ.get("AGENT_CONFIG_DIR", PROJECT_ROOT / "config")).expanduser()
MEMORY_FILE = WORKSPACE / "memory.md"
