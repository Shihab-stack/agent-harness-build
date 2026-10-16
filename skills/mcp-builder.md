# MCP Builder

Use this workflow when designing or scaffolding a new Model Context Protocol
(MCP) server that exposes a REST API, service, or internal data source as agent
tools.

## Design and safety

1. Clarify the data source, intended tool operations, caller, transport, and
   whether each operation is read-only or mutating. Expose the smallest useful
   tool surface; do not create a generic arbitrary-URL or arbitrary-query tool.
2. Inspect the repository's MCP SDK version and an existing server before
   choosing APIs. Prefer the SDK version already in use. Verify imports,
   registration methods, transport startup, and tool schemas against installed
   package code or official version-specific documentation.
3. Validate arguments with explicit types, bounds, and allowlists. Do not
   interpolate user-controlled values into shell commands or SQL. Use
   parameterized database queries and safe HTTP clients.
4. Read credentials from environment variables or a secret manager. Never
   hardcode, log, return, or put secrets in committed configuration. Return
   actionable errors without leaking tokens, headers, or private response
   bodies.
5. Set timeouts and response-size limits. Handle expected service errors
   explicitly, preserve cancellation, and avoid silent success-shaped
   fallbacks.
6. Default to the least privilege: read-only access, restricted network and
   filesystem scope, and explicit confirmation for destructive operations.
   Document any operations that mutate external state.

## Scaffold and integrate

1. Add a small module/package with one typed function per clear agent action.
   Give every tool a concise docstring, a stable name, and an explicit argument
   schema. Keep transport wiring separate from service logic where practical.
2. For the Python `mcp` SDK version used by this repository, the existing
   `src/agent_herness_build/sandbox_mcp.py` demonstrates `MCPServer`,
   `server.add_tool(function)`, and `server.run_stdio_async()`. Treat it as
   version-specific prior art and verify the installed API before copying it.
   If using a FastMCP release instead, confirm its import path and registration
   API in that exact release rather than mixing examples from different SDK
   versions.
3. For TypeScript, use the official `@modelcontextprotocol/sdk` and its
   documented stdio server/transport and tool-registration APIs for the
   installed SDK version. Do not invent method names from memory.
4. Register the process under a unique name in
   `config/mcp_servers.example.json` using `stdio`. Read secret values from
   environment variables; keep local credentials in ignored local config or
   the environment. Do not overwrite other user-specific server entries.
5. Add focused tests for valid arguments, invalid arguments, upstream errors,
   permission boundaries, and tool-schema registration. Mock remote services
   by default; keep live integration tests explicitly opt-in.
6. Update setup and security documentation. Verify the JSON parses, unit tests
   pass, and the server initializes and lists its expected tools when its
   dependencies and services are available. Clearly report any live checks
   that were not run.

## Minimal Python shape

Adapt this to the exact installed SDK API; do not assume it is drop-in code
across SDK versions:

```python
import asyncio
from mcp.server.mcpserver import MCPServer

server = MCPServer(name="example-service")


def health_check() -> str:
    """Return a non-sensitive service health summary."""
    return "ok"


server.add_tool(health_check)

if __name__ == "__main__":
    asyncio.run(server.run_stdio_async())
```
