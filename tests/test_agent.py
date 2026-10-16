"""Tests for local tool dispatch in the agent loop."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agent_herness_build.agent import call_tool, run_agent
from agent_herness_build.models import ModelConfig
from agent_herness_build.tools import files


class AgentToolDispatchTests(unittest.TestCase):
    """Check expected local tool errors without involving a model server."""

    def test_invalid_local_tool_arguments_are_reported(self) -> None:
        """Unexpected arguments become a tool error instead of a crash."""
        result = asyncio.run(call_tool("list_files", {"unexpected": True}, {}))
        self.assertIn("tool error: invalid arguments for list_files", result)

    def test_unknown_tools_are_reported(self) -> None:
        """Unknown tool names produce an explicit error."""
        result = asyncio.run(call_tool("not_a_tool", {}, {}))
        self.assertEqual(result, "error: unknown tool not_a_tool")

    def test_agent_streams_response_and_runs_tool_call(self) -> None:
        async def stream(*chunks):
            for chunk in chunks:
                yield chunk

        tool_call = SimpleNamespace(
            index=0,
            id="call-1",
            function=SimpleNamespace(name="list_files", arguments="{}"),
        )
        tool_chunk = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=None, tool_calls=[tool_call])
                )
            ]
        )
        answer_chunks = [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content="done", tool_calls=None)
                    )
                ]
            )
        ]
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(
                        side_effect=[stream(tool_chunk), stream(*answer_chunks)]
                    )
                )
            )
        )
        tokens: list[str] = []
        messages: list[dict] = []
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            files, "WORKSPACE", Path(temp_dir)
        ):
            answer = asyncio.run(
                run_agent(
                    "list files",
                    messages,
                    client,
                    ModelConfig("http://localhost:11434/v1", "ollama", "test"),
                    [],
                    {},
                    "(none)",
                    on_token=tokens.append,
                )
            )
        self.assertEqual(answer, "done")
        self.assertEqual(tokens, ["done"])
        self.assertEqual(
            [message["role"] for message in messages],
            ["system", "user", "assistant", "tool", "assistant"],
        )
        self.assertEqual(messages[-1]["content"], "done")

    def test_failed_turn_does_not_leave_partial_history(self) -> None:
        messages = [{"role": "system", "content": "old"}]
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(side_effect=RuntimeError("failed"))
                )
            )
        )
        with self.assertRaisesRegex(RuntimeError, "failed"):
            asyncio.run(
                run_agent(
                    "try",
                    messages,
                    client,
                    ModelConfig("http://localhost:11434/v1", "ollama", "test"),
                    [],
                    {},
                    "(none)",
                )
            )
        self.assertEqual(messages, [{"role": "system", "content": "old"}])

    def test_active_skill_is_added_to_system_prompt(self) -> None:
        async def stream(*chunks):
            for chunk in chunks:
                yield chunk

        answer_chunk = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content="done", tool_calls=None)
                )
            ]
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(side_effect=[stream(answer_chunk)])
                )
            )
        )
        messages: list[dict] = []
        with patch(
            "agent_herness_build.agent.load_skill",
            return_value="Always verify the exact failing behavior.",
        ):
            asyncio.run(
                run_agent(
                    "debug this",
                    messages,
                    client,
                    ModelConfig("http://localhost:11434/v1", "ollama", "test"),
                    [],
                    {},
                    "(none)",
                    active_skill="systematic-debugging",
                )
            )

        self.assertIn(
            "# Active behavioral skill: systematic-debugging",
            messages[0]["content"],
        )
        self.assertIn("Always verify the exact failing behavior.", messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
