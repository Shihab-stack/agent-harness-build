"""Example 2: read and write workspace files through a bounded tool loop."""

import json
import os
from pathlib import Path

from openai import OpenAI

client = OpenAI(
    base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
    api_key="ollama",
)
MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")

WORKSPACE = Path(__file__).resolve().parents[1] / "workspace"
MAX_TOOL_ROUNDS = 8


def workspace_path(filename: str) -> Path:
    """Resolve a filename and reject paths outside the assistant workspace."""
    root = WORKSPACE.resolve()
    path = (root / filename).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("file must be inside the assistant's workspace folder") from exc
    return path


def list_files() -> str:
    """List the files in the assistant's workspace folder."""
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    return "\n".join(p.name for p in WORKSPACE.iterdir()) or "(empty)"


def read_file(filename: str) -> str:
    """Read a file from the workspace folder."""
    try:
        path = workspace_path(filename)
    except ValueError as exc:
        return f"error: {exc}"
    if not path.is_file():
        return f"error: no file named {filename}"
    return path.read_text(encoding="utf-8")


def write_file(filename: str, content: str) -> str:
    """Write (or overwrite) a file in the workspace folder."""
    try:
        path = workspace_path(filename)
    except ValueError as exc:
        return f"error: {exc}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"wrote {filename}"


TOOLS = {"list_files": list_files, "read_file": read_file, "write_file": write_file}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List the files in the user's workspace folder.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read one file from the user's workspace folder.",
            "parameters": {
                "type": "object",
                "properties": {"filename": {"type": "string"}},
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write a file in the user's workspace folder.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["filename", "content"],
            },
        },
    },
]


def run_agent(user_message: str) -> str:
    """Run one user request through the model and bounded tool-call loop."""
    messages = [
        {"role": "system", "content": "You are a helpful personal assistant."},
        {"role": "user", "content": user_message},
    ]

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model=MODEL, messages=messages, tools=TOOL_SCHEMAS
        )
        message = response.choices[0].message

        if not message.tool_calls:
            return message.content or ""  # done - it answered

        messages.append(message)
        for call in message.tool_calls:
            args = json.loads(call.function.arguments or "{}")
            print(f"  [tool] {call.function.name}({args})")
            tool = TOOLS.get(call.function.name)
            if tool is None:
                result = f"error: unknown tool {call.function.name}"
            else:
                result = tool(**args)
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": result}
            )

    raise RuntimeError(f"Agent exceeded the limit of {MAX_TOOL_ROUNDS} tool rounds.")


if __name__ == "__main__":
    print(f"v2 agent ({MODEL}) - type /exit or press ctrl+c to quit")
    try:
        while True:
            question = input("\nyou: ")
            if question.strip().lower() in {"/exit", "/quit"}:
                break
            print("\nassistant:", run_agent(question))
    except (EOFError, KeyboardInterrupt):
        print("\nbye!")
