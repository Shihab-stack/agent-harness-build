"""Command-line interface for the local-first assistant."""

import argparse
import asyncio
from contextlib import AsyncExitStack

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from agent_herness_build.agent import LOCAL_TOOLS, run_agent
from agent_herness_build.conversations import load_conversation, save_conversation
from agent_herness_build.mcp import connect_mcp
from agent_herness_build.models import DEFAULT_MODEL, MODELS, check_ollama_model
from agent_herness_build.tools.files import FILE_TOOL_SCHEMAS
from agent_herness_build.tools.memory import MEMORY_TOOL, load_memory


def print_models(active_model: str) -> None:
    """Display available model backends and mark the active backend."""
    for name, config in MODELS.items():
        marker = "*" if name == active_model else " "
        print(f" {marker} {name:<12} {config.model} ({config.base_url})")


def print_tools(tool_schemas: list[dict]) -> None:
    """Display local and MCP tools currently registered with the CLI."""
    for schema in tool_schemas:
        function = schema["function"]
        origin = "local" if function["name"] in LOCAL_TOOLS else "mcp"
        print(f"  [{origin}] {function['name']}: {function.get('description', '')}")


def handle_command(
    line: str,
    active_model: str,
    tool_schemas: list[dict],
) -> tuple[bool, str]:
    """Handle a slash command and return whether chat should be skipped."""
    command, _, argument = line.partition(" ")
    argument = argument.strip()
    if command == "/models":
        print_models(active_model)
    elif command == "/model":
        if argument not in MODELS:
            print(f"Unknown model '{argument}'. Use /models to see choices.")
        else:
            active_model = argument
            print(f"Using {active_model} ({MODELS[active_model].model}).")
    elif command == "/tools":
        print_tools(tool_schemas)
    elif command == "/memory":
        print(load_memory())
    elif command == "/help":
        print(
            "Commands: /help, /models, /model <name>, /tools, /memory, "
            "/save <name>, /resume <name>, /quit"
        )
    elif command in {"/quit", "/exit"}:
        return True, active_model
    else:
        print("Unknown command. Use /help to see available commands.")
    return True, active_model


def request_error_message(error: Exception, backend: str, model: str) -> str:
    """Format model API failures as actionable messages for the CLI."""
    if backend.startswith("local"):
        if isinstance(error, APIStatusError) and error.status_code == 404:
            return (
                f"Ollama could not find model '{model}'. Install it with "
                f"`ollama pull {model}` or select an installed model using /model."
            )
        return (
            f"Could not get a response from Ollama ({error}). Check that Ollama "
            "is running and the selected model is installed, or select another "
            "model with /model, then try again."
        )
    if isinstance(error, APIStatusError):
        return f"Model request failed (HTTP {error.status_code}): {error.message}"
    return f"Could not reach the {backend} model service: {error}"


async def run_cli(initial_model: str, enable_mcp: bool) -> None:
    """Connect tools and run a conversation until the user exits."""
    if initial_model not in MODELS:
        available = ", ".join(MODELS)
        raise ValueError(f"Unknown model '{initial_model}'. Available: {available}")
    active_model = initial_model
    if active_model.startswith("local"):
        await asyncio.to_thread(
            check_ollama_model,
            MODELS[active_model].base_url,
            MODELS[active_model].model,
        )
    local_schemas = [*FILE_TOOL_SCHEMAS, MEMORY_TOOL]
    messages: list[dict] = []
    async with AsyncExitStack() as stack:
        if enable_mcp:
            mcp_schemas, mcp_routes = await connect_mcp(stack)
        else:
            mcp_schemas, mcp_routes = [], {}
        tool_schemas = [*local_schemas, *mcp_schemas]
        print(
            f"\nAgent ready — model: {active_model} "
            f"({MODELS[active_model].model}), {len(tool_schemas)} tools."
        )
        print(
            "Commands: /help, /models, /model <name>, /tools, /memory, "
            "/save <name>, /resume <name>, /quit\n"
        )
        try:
            while True:
                line = (await asyncio.to_thread(input, "you: ")).strip()
                if not line:
                    continue
                command = line.split(maxsplit=1)[0]
                if command in {"/save", "/resume"}:
                    _, _, name = line.partition(" ")
                    name = name.strip()
                    if not name:
                        print(f"Usage: {command} <name>")
                        continue
                    try:
                        if command == "/save":
                            print(save_conversation(name, messages))
                        else:
                            messages[:] = load_conversation(name)
                            print(f"resumed conversation '{name}'")
                    except (OSError, ValueError) as exc:
                        print(f"Could not {command[1:]} conversation: {exc}")
                    continue
                if line.startswith("/"):
                    previous_model = active_model
                    should_skip, active_model = handle_command(
                        line, active_model, tool_schemas
                    )
                    if command in {"/quit", "/exit"}:
                        break
                    if should_skip:
                        switched_to_local = (
                            active_model != previous_model
                            and active_model.startswith("local")
                        )
                        if switched_to_local:
                            try:
                                await asyncio.to_thread(
                                    check_ollama_model,
                                    MODELS[active_model].base_url,
                                    MODELS[active_model].model,
                                )
                            except RuntimeError as exc:
                                print(f"Cannot switch model: {exc}")
                                active_model = previous_model
                        continue
                model = MODELS[active_model]
                client = AsyncOpenAI(base_url=model.base_url, api_key=model.api_key)
                try:
                    print("\nassistant: ", end="", flush=True)
                    await run_agent(
                        line,
                        messages,
                        client,
                        model,
                        tool_schemas,
                        mcp_routes,
                        load_memory(),
                        on_token=lambda text: print(text, end="", flush=True),
                    )
                    print("\n")
                except (APIConnectionError, APITimeoutError, APIStatusError) as exc:
                    message = request_error_message(exc, active_model, model.model)
                    print(f"\n{message}\n")
                finally:
                    await client.close()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")


def main() -> None:
    """Parse startup options and launch the interactive asynchronous CLI."""
    parser = argparse.ArgumentParser(
        description="Run the local-first assistant with optional MCP tools."
    )
    parser.add_argument(
        "--model",
        choices=MODELS,
        default=DEFAULT_MODEL,
        help="initial model backend (default: local Ollama)",
    )
    parser.add_argument(
        "--no-mcp",
        action="store_true",
        help="start without MCP servers; local file and memory tools remain available",
    )
    args = parser.parse_args()
    try:
        asyncio.run(run_cli(args.model, enable_mcp=not args.no_mcp))
    except RuntimeError as exc:
        parser.exit(1, f"{parser.prog}: error: {exc}\n")
