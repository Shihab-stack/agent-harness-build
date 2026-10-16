"""Persistent plain-text memory stored separately from user workspace files."""

from agent_herness_build.paths import MEMORY_FILE


def load_memory() -> str:
    """Load saved facts or return a message when the memory file is absent."""
    if not MEMORY_FILE.is_file():
        return "(nothing saved yet)"
    return MEMORY_FILE.read_text(encoding="utf-8")


def save_memory(fact: str) -> str:
    """Append a lasting user fact to the local memory file."""
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with MEMORY_FILE.open("a", encoding="utf-8") as memory_file:
        memory_file.write(f"- {fact}\n")
    return f"saved: {fact}"


MEMORY_TOOL = {
    "type": "function",
    "function": {
        "name": "save_memory",
        "description": "Save one useful, lasting fact about the user.",
        "parameters": {
            "type": "object",
            "properties": {"fact": {"type": "string"}},
            "required": ["fact"],
            "additionalProperties": False,
        },
    },
}
