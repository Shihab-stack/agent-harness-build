# Deep Reasoning

Use this workflow for genuinely complex logic, math, architecture, or coding
problems. Do not invoke extra reasoning tools for straightforward requests.

1. Check the tools registered in the current session and identify the
   Sequential Thinking tool exposed by the `sequential-thinking` MCP server.
   The harness prefixes MCP tool names; use the actual registered name rather
   than assuming a particular spelling.
2. Before answering a complex task, use that tool to structure the work into
   smaller, verifiable steps. State the problem and relevant constraints,
   examine assumptions, and check intermediate results.
3. Use other available tools, source material, calculations, or tests to verify
   conclusions when appropriate. A reasoning tool does not by itself guarantee
   correctness.
4. If the server or tool is unavailable or returns an error, say that it was
   unavailable and continue carefully using available evidence. Never claim the
   tool was called when it was not.
5. Give the user a concise summary of the approach, key checks, and conclusion.
   Do not reveal private hidden chain-of-thought or provide a verbatim dump of
   internal reasoning.
