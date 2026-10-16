"""Tests for Docker sandbox command construction and MCP tool behavior."""

import io
import asyncio
import unittest
from unittest.mock import patch

from agent_herness_build import sandbox_mcp


class CapturingInput(io.BytesIO):
    def close(self) -> None:
        self.was_closed = True


class FakeProcess:
    def __init__(self) -> None:
        self.stdin = CapturingInput()
        self.stdin.was_closed = False
        self.stdout = io.BytesIO(b"sandbox output\n")
        self.stderr = io.BytesIO()

    def poll(self) -> int:
        return 0

    def wait(self, timeout: float | None = None) -> int:
        return 0


class SandboxTests(unittest.TestCase):
    def test_docker_command_enforces_isolation_and_resource_limits(self) -> None:
        with patch.object(sandbox_mcp.shutil, "which", return_value="/usr/bin/docker"):
            command = sandbox_mcp._docker_command("agent-harness-test")

        self.assertIn("--network=none", command)
        self.assertIn("--cpus=0.5", command)
        self.assertIn("--memory=256m", command)
        self.assertIn("--memory-swap=256m", command)
        self.assertIn("--read-only", command)
        self.assertIn("--cap-drop=ALL", command)
        self.assertIn("--security-opt=no-new-privileges", command)
        self.assertIn("--pull=never", command)
        self.assertNotIn("-v", command)
        self.assertNotIn("--mount", command)
        self.assertEqual(command[-3:], ["python", "-I", "-"])

    def test_docker_missing_is_reported(self) -> None:
        with patch.object(sandbox_mcp.shutil, "which", return_value=None):
            result = sandbox_mcp.run_script("print('hello')")
        self.assertIn("Docker CLI not found", result)

    def test_empty_or_oversized_code_is_rejected(self) -> None:
        self.assertTrue(sandbox_mcp.run_script("  ").startswith("error:"))
        oversized = "x" * (sandbox_mcp.MAX_SCRIPT_BYTES + 1)
        self.assertIn("byte limit", sandbox_mcp.run_script(oversized))
        self.assertIn(
            "valid Unicode",
            sandbox_mcp.run_script("\ud800"),
        )

    def test_script_is_passed_as_stdin_without_shell_interpolation(self) -> None:
        process = FakeProcess()
        script = "print('safe $HOME; no shell')"
        with (
            patch.object(sandbox_mcp.shutil, "which", return_value="/usr/bin/docker"),
            patch.object(sandbox_mcp.subprocess, "Popen", return_value=process) as popen,
        ):
            result = sandbox_mcp.run_script(script)

        command = popen.call_args.args[0]
        self.assertEqual(process.stdin.getvalue(), script.encode())
        self.assertTrue(process.stdin.was_closed)
        self.assertIn("stdout:\nsandbox output", result)
        self.assertEqual(command[-3:], ["python", "-I", "-"])
        self.assertNotIn(script, command)

    def test_mcp_registers_run_script_tool(self) -> None:
        tools = asyncio.run(sandbox_mcp.server.list_tools())
        self.assertEqual([tool.name for tool in tools], ["run_script"])
        self.assertIn("python_code", tools[0].input_schema["properties"])


if __name__ == "__main__":
    unittest.main()
