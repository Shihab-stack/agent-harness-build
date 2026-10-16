"""Tests for CLI commands and model request diagnostics."""

import asyncio
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx2
from openai import APIConnectionError, APIStatusError
from agent_herness_build import cli, conversations


class CLITests(unittest.TestCase):
    def test_help_command_lists_available_commands(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            skipped, active_model = cli.handle_command("/help", "local", [])
        self.assertTrue(skipped)
        self.assertEqual(active_model, "local")
        self.assertIn("/save <name>", output.getvalue())
        self.assertIn("/resume <name>", output.getvalue())

    def test_local_model_request_error_is_actionable(self) -> None:
        message = cli.request_error_message(
            RuntimeError("model missing"), "local-small", "qwen3.5:2b"
        )
        self.assertIn("Ollama", message)
        self.assertIn("/model", message)

    def test_missing_ollama_model_error_suggests_install(self) -> None:
        request = httpx2.Request("POST", "http://localhost:11434/v1/chat/completions")
        response = httpx2.Response(404, request=request)
        error = APIStatusError("model missing", response=response, body=None)
        message = cli.request_error_message(error, "local-small", "qwen3.5:2b")
        self.assertIn("ollama pull qwen3.5:2b", message)

    def test_request_failure_does_not_exit_interactive_cli(self) -> None:
        request = httpx2.Request("POST", "http://localhost:11434/v1/chat/completions")
        client = SimpleNamespace(close=AsyncMock())
        output = io.StringIO()
        with (
            patch.object(cli, "check_ollama_model"),
            patch.object(cli, "AsyncOpenAI", return_value=client),
            patch.object(
                cli,
                "run_agent",
                AsyncMock(
                    side_effect=[
                        APIConnectionError(message="offline", request=request),
                        "recovered",
                    ]
                ),
            ) as run_agent,
            patch.object(cli, "load_memory", return_value=""),
            patch(
                "builtins.input",
                side_effect=["first request", "second request", "/quit"],
            ),
            redirect_stdout(output),
        ):
            asyncio.run(cli.run_cli("local", enable_mcp=False))
        self.assertEqual(run_agent.await_count, 2)
        self.assertIn("try again", output.getvalue())
        self.assertEqual(output.getvalue().count("assistant:"), 2)

    def test_cli_handles_help_save_resume_and_exit(self) -> None:
        output = io.StringIO()
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.object(conversations, "WORKSPACE", Path(temp_dir)),
            patch.object(cli, "check_ollama_model"),
            patch(
                "builtins.input",
                side_effect=["/save routine", "/resume routine", "/help", "/quit"],
            ),
            redirect_stdout(output),
        ):
            asyncio.run(cli.run_cli("local", enable_mcp=False))
            self.assertTrue(
                (Path(temp_dir) / "conversations" / "routine.json").is_file()
            )
        self.assertIn("saved conversation 'routine'", output.getvalue())
        self.assertIn("resumed conversation 'routine'", output.getvalue())

    def test_unavailable_model_switch_is_rejected(self) -> None:
        output = io.StringIO()
        with (
            patch.object(
                cli,
                "check_ollama_model",
                side_effect=[None, RuntimeError("model missing")],
            ),
            patch(
                "builtins.input",
                side_effect=["/model local-small", "/models", "/quit"],
            ),
            redirect_stdout(output),
        ):
            asyncio.run(cli.run_cli("local", enable_mcp=False))
        self.assertIn("Cannot switch model: model missing", output.getvalue())
        self.assertIn("* local", output.getvalue())


if __name__ == "__main__":
    unittest.main()
