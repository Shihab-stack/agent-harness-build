"""Example 1: list and read files using model-selected tool calls."""

import sys

sys.stdout.reconfigure(encoding="utf-8")  # so emoji don't crash the Windows console

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


# --- the actual tools: plain Python functions -------------------------------

def list_files() -> str:
    """Return the names of files in the assistant's workspace."""
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    return "\n".join(p.name for p in WORKSPACE.iterdir()) or "(empty)"


def read_file(filename: str) -> str:
    """Read a file from the workspace while preventing path traversal."""
    root = WORKSPACE.resolve()
    path = (WORKSPACE / filename).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return "error: file must be inside the assistant's workspace folder"
    if not path.is_file():
        return f"error: no file named {filename}"
    return path.read_text(encoding="utf-8")


TOOLS = {"list_files": list_files, "read_file": read_file}

# --- what the model sees: a JSON description of each tool -------------------

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
]


def chat(user_message: str) -> str:
    """Answer one user message, executing at most one round of tool calls."""
    messages = [
        {"role": "system", "content": "You are a helpful personal assistant."},
        {"role": "user", "content": user_message},
    ]

    response = client.chat.completions.create(
        model=MODEL, messages=messages, tools=TOOL_SCHEMAS
    )
    message = response.choices[0].message

    # The model didn't want a tool - just answer.
    if not message.tool_calls:
        return message.content or ""

    # Run the tool it asked for and give it the result... ONCE.
    messages.append(message)
    for call in message.tool_calls:
        args = json.loads(call.function.arguments or "{}")
        print(f"  [tool] {call.function.name}({args})")
        result = TOOLS[call.function.name](**args)
        messages.append(
            {"role": "tool", "tool_call_id": call.id, "content": result}
        )

    final = client.chat.completions.create(model=MODEL, messages=messages)
    return final.choices[0].message.content


if __name__ == "__main__":
    print(f"v1 assistant ({MODEL}) - ctrl+c to quit")
    try:
        while True:
            question = input("\nyou: ")
            print("\nassistant:", chat(question))
    except (EOFError, KeyboardInterrupt):
        print("\nbye!")
