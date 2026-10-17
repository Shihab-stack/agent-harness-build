"""Tests for the committed example MCP server configuration."""

import json
import unittest

from agent_herness_build.paths import PROJECT_ROOT


class MCPConfigTests(unittest.TestCase):
    def test_example_config_contains_sequential_thinking_server(self) -> None:
        config_path = PROJECT_ROOT / "config" / "mcp_servers.example.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        servers = config["mcpServers"]

        self.assertEqual(
            servers["sequential-thinking"],
            {
                "command": "npx",
                "args": [
                    "-y",
                    "@modelcontextprotocol/server-sequential-thinking@1.0.0",
                ],
            },
        )
        self.assertIn("context7", servers)
        self.assertIn("playwright", servers)
        self.assertIn("sandbox", servers)
        self.assertNotIn("@latest", json.dumps(servers))

    def test_published_mcp_packages_are_version_pinned(self) -> None:
        config_path = PROJECT_ROOT / "config" / "mcp_servers.example.json"
        servers = json.loads(config_path.read_text(encoding="utf-8"))["mcpServers"]
        for server_name in (
            "memory",
            "github",
            "context7",
            "playwright",
            "sequential-thinking",
        ):
            with self.subTest(server=server_name):
                package_argument = next(
                    argument
                    for argument in servers[server_name]["args"]
                    if argument.startswith("@")
                )
                self.assertRegex(package_argument, r"@[^@]+@\d")
        for server_name in ("time", "fetch"):
            with self.subTest(server=server_name):
                args = servers[server_name]["args"]
                self.assertEqual(args[0], "--from")
                self.assertRegex(args[1], r"==\d")


if __name__ == "__main__":
    unittest.main()
