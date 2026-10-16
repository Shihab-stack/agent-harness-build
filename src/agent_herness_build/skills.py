"""Discover and load on-demand behavioral skills from the project root."""

import re
from pathlib import Path

from agent_herness_build.paths import PROJECT_ROOT

SKILLS_DIR = PROJECT_ROOT / "skills"
SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def list_skills() -> list[str]:
    """Return the names of readable skill files in the project skills folder."""
    if not SKILLS_DIR.exists():
        return []
    return sorted(
        path.stem
        for path in SKILLS_DIR.glob("*.md")
        if path.is_file() and SKILL_NAME.fullmatch(path.stem)
    )


def load_skill(name: str) -> str:
    """Load one skill by safe, exact filename and return its Markdown content."""
    if not SKILL_NAME.fullmatch(name):
        raise ValueError("skill name must contain lowercase letters, digits, and hyphens")

    root = SKILLS_DIR.resolve()
    path = (root / f"{name}.md").resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("skill file must stay inside the skills directory") from exc
    if not path.is_file():
        raise ValueError(f"no skill named '{name}'")

    try:
        content = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"could not read skill '{name}': {exc}") from exc
    if not content:
        raise ValueError(f"skill '{name}' is empty")
    return content
