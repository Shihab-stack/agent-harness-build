"""Model/tool orchestration for the interactive assistant."""

import inspect
import json
from typing import Any, Awaitable, Callable

from openai import AsyncOpenAI

from agent_herness_build.mcp import MCPRoute, call_mcp_tool
from agent_herness_build.models import ModelConfig
from agent_herness_build.skills import load_skill
from agent_herness_build.tools.files import FILE_TOOLS
from agent_herness_build.tools.memory import save_memory

MAX_TOOL_ROUNDS = 8
LOCAL_TOOLS = {**FILE_TOOLS, "save_memory": save_memory}
SYSTEM_PROMPT = """You are a helpful personal assistant. Be concise.

Use list_project_files and read_project_file for read-only inspection of
allowlisted project files. Never use project inspection to access credentials
or local configuration. The regular file tools operate on the user's workspace;
write_file can create files only under workspace/generated/ and asks before
overwriting. Use save_memory for useful lasting facts the user shares. Use only
the sandbox tool for Python code; never route code execution through another
Python MCP server. Use only provided tools for time and web fetch tasks. Be
clear about tool errors. For library/framework questions, consult Context7's
version-specific documentation tools when available. For browser or web-app
tasks, use the Playwright MCP tools when available and report what was actually
tested. MCP tools that are not explicitly marked read-only require user
confirmation; if an action is denied, do not retry it or claim it succeeded.
Do not repeat credentials or sensitive tool arguments in the final response.

Remembered facts:
{memory}"""


async def call_tool(
    name: str,
    args: dict[str, Any],
    mcp_routes: dict[str, MCPRoute],
) -> str:
    """Validate and dispatch a local tool call or route it to an MCP server."""
    local_tool = LOCAL_TOOLS.get(name)
    if local_tool is not None:
        try:
            inspect.signature(local_tool).bind(**args)
        except TypeError as exc:
            return f"tool error: invalid arguments for {name}: {exc}"
        return local_tool(**args)
    return await call_mcp_tool(name, args, mcp_routes)


async def _confirm_mcp_tool(
    name: str,
    routes: dict[str, MCPRoute],
    confirm_action: Callable[[str, str], bool | Awaitable[bool]] | None,
) -> bool:
    route = routes.get(name)
    if route is None or not route.requires_confirmation:
        return True
    if confirm_action is None:
        return False
    approved = confirm_action(name, route.description)
    if inspect.isawaitable(approved):
        return await approved
    return approved


def _tool_log_name(name: str, mcp_routes: dict[str, MCPRoute]) -> str:
    if name in LOCAL_TOOLS or name in mcp_routes:
        return name
    return "unregistered"


async def run_agent(
    prompt: str,
    messages: list[dict[str, Any]],
    client: AsyncOpenAI,
    model: ModelConfig,
    tool_schemas: list[dict[str, Any]],
    mcp_routes: dict[str, MCPRoute],
    memory: str,
    on_token: Callable[[str], None] | None = None,
    active_skill: str | None = None,
    confirm_action: Callable[[str, str], bool | Awaitable[bool]] | None = None,
    temperature: float | None = None,
) -> str:
    """Stream a turn, run any requested tools, and retain completed history."""
    previous_messages = list(messages)
    system_prompt = SYSTEM_PROMPT.format(memory=memory)
    if active_skill is not None:
        skill_instructions = load_skill(active_skill)
        system_prompt += (
            f"\n\n# Active behavioral skill: {active_skill}\n"
            f"{skill_instructions}"
        )
    if messages:
        messages[0] = {
            "role": "system",
            "content": system_prompt,
        }
    else:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    completed = False
    try:
        for _ in range(MAX_TOOL_ROUNDS):
            request_options: dict[str, Any] = {}
            if temperature is not None:
                request_options["temperature"] = temperature
            response = await client.chat.completions.create(
                model=model.model,
                messages=messages,
                tools=tool_schemas or None,
                stream=True,
                max_tokens=model.max_output_tokens,
                **request_options,
            )
            tool_calls: dict[int, dict[str, Any]] = {}
            answer_parts: list[str] = []
            async for chunk in response:
                delta = chunk.choices[0].delta
                if delta.content:
                    answer_parts.append(delta.content)
                    if on_token is not None:
                        on_token(delta.content)
                for tool_delta in delta.tool_calls or []:
                    tool_call = tool_calls.setdefault(
                        tool_delta.index,
                        {
                            "id": "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        },
                    )
                    if tool_delta.id:
                        tool_call["id"] = tool_delta.id
                    if tool_delta.function:
                        if tool_delta.function.name:
                            tool_call["function"]["name"] += tool_delta.function.name
                        if tool_delta.function.arguments:
                            tool_call["function"]["arguments"] += (
                                tool_delta.function.arguments
                            )

            answer = "".join(answer_parts)
            if not tool_calls:
                messages.append({"role": "assistant", "content": answer})
                completed = True
                return answer

            ordered_tool_calls = [tool_calls[index] for index in sorted(tool_calls)]
            messages.append(
                {
                    "role": "assistant",
                    "content": answer or None,
                    "tool_calls": ordered_tool_calls,
                }
            )
            for tool_call in ordered_tool_calls:
                try:
                    arguments = json.loads(tool_call["function"]["arguments"] or "{}")
                except json.JSONDecodeError as exc:
                    result = f"tool error: invalid JSON arguments: {exc}"
                else:
                    if not isinstance(arguments, dict):
                        result = "tool error: arguments must be a JSON object"
                    else:
                        tool_name = tool_call["function"]["name"]
                        log_name = _tool_log_name(tool_name, mcp_routes)
                        result = ""
                        try:
                            approved = await _confirm_mcp_tool(
                                tool_name, mcp_routes, confirm_action
                            )
                        except Exception as exc:
                            result = (
                                f"tool not run: confirmation failed "
                                f"({type(exc).__name__})"
                            )
                            approved = False
                        if not approved and not result:
                            result = (
                                "tool not run: confirmation was denied or unavailable"
                            )
                            print(f"  [tool] denied {log_name}")
                        elif not approved:
                            print(f"  [tool] confirmation failed {log_name}")
                        elif approved:
                            print(f"  [tool] calling {log_name}")
                            try:
                                result = await call_tool(
                                    tool_name, arguments, mcp_routes
                                )
                            except Exception as exc:
                                result = (
                                    f"tool error calling {tool_name}: "
                                    f"{type(exc).__name__}: {exc}"
                                )
                            status = (
                                "failed"
                                if result.startswith(("error:", "tool error"))
                                else "completed"
                            )
                            print(f"  [tool] {status} {log_name}")
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": result,
                    }
                )

        raise RuntimeError(
            f"Agent exceeded the limit of {MAX_TOOL_ROUNDS} tool rounds."
        )
    finally:
        if not completed:
            messages[:] = previous_messages
