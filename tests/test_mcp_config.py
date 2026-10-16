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
                    "@modelcontextprotocol/server-sequential-thinking",
                ],
            },
        )
        self.assertIn("context7", servers)
        self.assertIn("playwright", servers)
        self.assertIn("sandbox", servers)


if __name__ == "__main__":
    unittest.main()
