"""Command-line interface for the local-first assistant."""

import argparse
import asyncio
import os
from contextlib import AsyncExitStack

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from agent_herness_build.agent import LOCAL_TOOLS, run_agent
from agent_herness_build.conversations import load_conversation, save_conversation
from agent_herness_build.mcp import DEFAULT_STARTUP_TIMEOUT, connect_mcp
from agent_herness_build.models import (
    DEFAULT_MODEL,
    MODELS,
    check_ollama_model,
    fallback_models,
    model_is_configured,
    required_api_key,
)
from agent_herness_build.skills import list_skills, load_skill
from agent_herness_build.tools.files import FILE_TOOL_SCHEMAS
from agent_herness_build.tools.memory import MEMORY_TOOL, load_memory


def print_models(active_model: str) -> None:
    """Display available model backends and mark the active backend."""
    for name, config in MODELS.items():
        marker = "*" if name == active_model else " "
        availability = "" if model_is_configured(name) else " [not configured]"
        print(
            f" {marker} {name:<12} {config.model} "
            f"({config.base_url}){availability}"
        )


def print_tools(tool_schemas: list[dict]) -> None:
    """Display local and MCP tools currently registered with the CLI."""
    for schema in tool_schemas:
        function = schema["function"]
        origin = "local" if function["name"] in LOCAL_TOOLS else "mcp"
        print(f"  [{origin}] {function['name']}: {function.get('description', '')}")


def confirm_mcp_action(tool_name: str, description: str) -> bool:
    """Require interactive approval for an MCP tool that may mutate state."""
    print(f"\nMCP action requires confirmation: {tool_name}")
    print(f"Operation: {description}")
    try:
        answer = input("Allow this action? [y/N] ").strip().lower()
    except EOFError:
        print("Confirmation unavailable; action denied.")
        return False
    if answer not in {"y", "yes"}:
        print("Action denied.")
        return False
    return True


def handle_skill_command(line: str, active_skill: str | None) -> tuple[bool, str | None]:
    """List, activate, or deactivate a behavioral skill."""
    command, _, argument = line.partition(" ")
    argument = argument.strip()
    if command == "/skills":
        available = list_skills()
        print("Available skills: " + (", ".join(available) if available else "(none)"))
        if active_skill:
            print(f"Active skill: {active_skill}")
        return True, active_skill
    if command != "/skill":
        return False, active_skill
    if not argument:
        print("Usage: /skill <name|off>. Use /skills to list skills.")
        return True, active_skill
    if argument == "off":
        print(f"Deactivated skill '{active_skill}'." if active_skill else "No skill is active.")
        return True, None
    try:
        load_skill(argument)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Could not activate skill: {exc}")
        return True, active_skill
    print(f"Activated skill '{argument}'. Use /skill off to deactivate it.")
    return True, argument


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
        elif not model_is_configured(argument):
            required_key = required_api_key(argument)
            print(f"Cannot switch model: set {required_key} first.")
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
            "/skills, /skill <name|off>, "
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
        if error.status_code == 429:
            return (
                f"{backend} reached its rate or usage limit (HTTP 429). "
                "No configured fallback model is available."
            )
        return f"Model request failed (HTTP {error.status_code}): {error.message}"
    return f"Could not reach the {backend} model service: {error}"


async def run_cli(
    initial_model: str,
    enable_mcp: bool,
    selected_mcp_servers: set[str] | None = None,
    mcp_startup_timeout: float = DEFAULT_STARTUP_TIMEOUT,
) -> None:
    """Connect tools and run a conversation until the user exits."""
    if initial_model not in MODELS:
        available = ", ".join(MODELS)
        raise ValueError(f"Unknown model '{initial_model}'. Available: {available}")
    if not model_is_configured(initial_model):
        required_key = required_api_key(initial_model)
        raise ValueError(f"Model '{initial_model}' requires {required_key}.")
    active_model = initial_model
    active_skill: str | None = None
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
            mcp_schemas, mcp_routes = await connect_mcp(
                stack,
                selected_servers=selected_mcp_servers,
                startup_timeout=mcp_startup_timeout,
            )
        else:
            mcp_schemas, mcp_routes = [], {}
            print("  [mcp] all servers disabled (--no-mcp)")
        tool_schemas = [*local_schemas, *mcp_schemas]
        print(
            f"\nAgent ready — model: {active_model} "
            f"({MODELS[active_model].model}), {len(tool_schemas)} tools."
        )
        print(
            "Commands: /help, /models, /model <name>, /tools, /memory, "
            "/skills, /skill <name|off>, "
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
                skill_handled, active_skill = handle_skill_command(
                    line, active_skill
                )
                if skill_handled:
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
                candidates = [active_model]
                while candidates:
                    selected_model = candidates.pop(0)
                    if (
                        selected_model != active_model
                        and selected_model.startswith("local")
                    ):
                        try:
                            await asyncio.to_thread(
                                check_ollama_model,
                                MODELS[selected_model].base_url,
                                MODELS[selected_model].model,
                            )
                        except RuntimeError as exc:
                            print(f"Skipping fallback {selected_model}: {exc}")
                            continue
                    if selected_model != active_model:
                        active_model = selected_model
                        print(
                            f"\nSwitching to fallback model: {active_model} "
                            f"({MODELS[active_model].model})."
                        )
                    model = MODELS[active_model]
                    client = AsyncOpenAI(
                        base_url=model.base_url, api_key=model.api_key
                    )
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
                            active_skill=active_skill,
                            confirm_action=confirm_mcp_action,
                        )
                        print("\n")
                        break
                    except (
                        APIConnectionError,
                        APITimeoutError,
                        APIStatusError,
                    ) as exc:
                        if isinstance(exc, APIStatusError):
                            fallback = fallback_models(active_model, exc.status_code)
                            if fallback:
                                candidates = fallback
                                if exc.status_code == 413:
                                    reason = "rejected the request size"
                                else:
                                    reason = "reached its rate or usage limit"
                                print(f"\n{active_model} {reason}; trying a fallback.")
                                continue
                        message = request_error_message(
                            exc, active_model, model.model
                        )
                        print(f"\n{message}\n")
                        break
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
        help=(
            "initial model backend "
            "(default: configured cloud provider or local Ollama)"
        ),
    )
    parser.add_argument(
        "--no-mcp",
        action="store_true",
        help="start without MCP servers; local file and memory tools remain available",
    )
    parser.add_argument(
        "--mcp-servers",
        type=parse_mcp_servers,
        metavar="NAME,NAME",
        help="enable only these configured MCP servers (default: all)",
    )
    parser.add_argument(
        "--mcp-startup-timeout",
        type=float,
        default=os.environ.get(
            "AGENT_MCP_STARTUP_TIMEOUT", str(DEFAULT_STARTUP_TIMEOUT)
        ),
        metavar="SECONDS",
        help="per-server startup timeout (default: AGENT_MCP_STARTUP_TIMEOUT or 20)",
    )
    args = parser.parse_args()
    if args.no_mcp and args.mcp_servers is not None:
        parser.error("--mcp-servers cannot be used together with --no-mcp")
    if args.mcp_startup_timeout <= 0:
        parser.error("--mcp-startup-timeout must be positive")
    try:
        asyncio.run(
            run_cli(
                args.model,
                enable_mcp=not args.no_mcp,
                selected_mcp_servers=args.mcp_servers,
                mcp_startup_timeout=args.mcp_startup_timeout,
            )
        )
    except (RuntimeError, ValueError) as exc:
        parser.exit(1, f"{parser.prog}: error: {exc}\n")


def parse_mcp_servers(value: str) -> set[str]:
    """Parse a comma-separated MCP server allowlist."""
    names = [name.strip() for name in value.split(",")]
    if any(not name for name in names):
        raise argparse.ArgumentTypeError("provide comma-separated server names")
    if len(set(names)) != len(names):
        raise argparse.ArgumentTypeError("server names must not be repeated")
    return set(names)
