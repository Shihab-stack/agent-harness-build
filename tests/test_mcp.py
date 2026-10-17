"""Tests for resilient MCP startup, selection, and tool safety metadata."""

import asyncio
import io
import unittest
from contextlib import AsyncExitStack, redirect_stdout
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agent_herness_build import mcp


def fake_tool(
    name: str,
    *,
    read_only: bool | None = None,
    destructive: bool | None = None,
    input_schema: dict | None = None,
) -> SimpleNamespace:
    annotations = (
        SimpleNamespace(
            read_only_hint=read_only,
            destructive_hint=destructive,
        )
        if read_only is not None or destructive is not None
        else None
    )
    return SimpleNamespace(
        name=name,
        description=f"Description for {name}",
        input_schema=input_schema or {"type": "object", "properties": {}},
        annotations=annotations,
    )


class MCPLoadingTests(unittest.TestCase):
    def test_connection_failure_does_not_prevent_other_servers(self) -> None:
        async def connect(stack, name, spec):
            if name == "broken":
                raise RuntimeError("server unavailable")
            return [], {}

        output = io.StringIO()
        with (
            patch.object(
                mcp,
                "load_server_config",
                return_value={
                    "broken": {"command": "broken"},
                    "working": {"command": "working"},
                    "not-selected": {"command": "unused"},
                },
            ),
            patch.object(mcp, "_connect_server", side_effect=connect),
            redirect_stdout(output),
        ):
            schemas, routes = asyncio.run(
                mcp.connect_mcp(AsyncExitStack(), selected_servers={"broken", "working"})
            )

        self.assertEqual(schemas, [])
        self.assertEqual(routes, {})
        self.assertIn("[mcp] failed 'broken': RuntimeError: server unavailable", output.getvalue())
        self.assertIn("[mcp] connected 'working': 0 tool(s)", output.getvalue())
        self.assertIn("[mcp] disabled 'not-selected'", output.getvalue())

    def test_startup_timeout_closes_partial_server_resources(self) -> None:
        closed: list[bool] = []

        class Resource:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, traceback):
                closed.append(True)

        async def hang_after_opening_resource(stack, name, spec):
            await stack.enter_async_context(Resource())
            await asyncio.sleep(1)

        output = io.StringIO()
        with (
            patch.object(
                mcp,
                "load_server_config",
                return_value={"slow": {"command": "slow"}},
            ),
            patch.object(mcp, "_connect_server", side_effect=hang_after_opening_resource),
            redirect_stdout(output),
        ):
            schemas, routes = asyncio.run(
                mcp.connect_mcp(AsyncExitStack(), startup_timeout=0.01)
            )

        self.assertEqual((schemas, routes), ([], {}))
        self.assertEqual(closed, [True])
        self.assertIn("startup timed out after 0.01s", output.getvalue())

    def test_unknown_server_selection_is_rejected_before_startup(self) -> None:
        with patch.object(mcp, "load_server_config", return_value={"time": {}}):
            with self.assertRaisesRegex(ValueError, "Unknown MCP server"):
                asyncio.run(
                    mcp.connect_mcp(AsyncExitStack(), selected_servers={"missing"})
                )

    def test_invalid_startup_timeout_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "finite positive"):
            asyncio.run(mcp.connect_mcp(AsyncExitStack(), startup_timeout=0))

    def test_invalid_tool_schema_rejects_server_registration(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid input schema"):
            mcp._tool_entries(
                "example",
                AsyncMock(),
                [fake_tool("broken", input_schema={"type": "string"})],
            )

    def test_invalid_tool_name_rejects_server_registration(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid name"):
            mcp._tool_entries("example", AsyncMock(), [fake_tool("bad tool name")])

    def test_startup_error_redacts_secret_environment_and_arguments(self) -> None:
        error = RuntimeError("failed with token-123 and api-key-456")
        message = mcp._safe_startup_error(
            error,
            {
                "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "token-123"},
                "args": ["--api-key", "api-key-456"],
            },
        )
        self.assertNotIn("token-123", message)
        self.assertNotIn("api-key-456", message)
        self.assertEqual(message, "failed with [redacted] and [redacted]")

    def test_unknown_or_mutating_tools_require_confirmation(self) -> None:
        _, routes = mcp._tool_entries(
            "example",
            AsyncMock(),
            [
                fake_tool("read", read_only=True),
                fake_tool("write", read_only=False),
                fake_tool("unclassified"),
                fake_tool("destructive", read_only=True, destructive=True),
            ],
        )
        self.assertFalse(routes["mcp_example_read"].requires_confirmation)
        self.assertTrue(routes["mcp_example_write"].requires_confirmation)
        self.assertTrue(routes["mcp_example_unclassified"].requires_confirmation)
        self.assertTrue(routes["mcp_example_destructive"].requires_confirmation)


class MCPToolCallTests(unittest.TestCase):
    def test_mcp_tool_exception_becomes_explicit_tool_error(self) -> None:
        route = mcp.MCPRoute(
            session=AsyncMock(),
            server_tool_name="lookup",
            description="Look up a record",
            requires_confirmation=False,
        )
        route.session.call_tool.side_effect = RuntimeError("upstream unavailable")
        result = asyncio.run(
            mcp.call_mcp_tool("mcp_example_lookup", {}, {"mcp_example_lookup": route})
        )
        self.assertIn("tool error calling mcp_example_lookup", result)
        self.assertIn("upstream unavailable", result)


if __name__ == "__main__":
    unittest.main()
