"""Telegram long-polling interface for the agent harness."""

import argparse
import asyncio
import logging
import math
import os
import secrets
import signal
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from openai import APIStatusError, AsyncOpenAI
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from agent_herness_build.agent import run_agent
from agent_herness_build.mcp import DEFAULT_STARTUP_TIMEOUT, MCPRoute, connect_mcp
from agent_herness_build.models import (
    DEFAULT_MODEL,
    MODELS,
    ModelConfig,
    check_ollama_model,
    fallback_models,
    required_api_key,
)
from agent_herness_build.tools.files import FILE_TOOL_SCHEMAS
from agent_herness_build.tools.memory import MEMORY_TOOL, load_memory

MAX_INPUT_LENGTH = 8_000
MAX_TELEGRAM_MESSAGE_LENGTH = 4_096
MAX_HISTORY_TURNS = 10
CONFIRMATION_TIMEOUT = 60.0
logger = logging.getLogger(__name__)


class _TokenRedactionFilter(logging.Filter):
    """Prevent Telegram API tokens from appearing in dependency log output."""

    def __init__(self, token: str) -> None:
        super().__init__()
        self.token = token

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if self.token in message:
            record.msg = message.replace(self.token, "[redacted]")
            record.args = ()
        if record.exc_info is not None:
            exception_text = logging.Formatter().formatException(record.exc_info)
            record.exc_text = exception_text.replace(self.token, "[redacted]")
            record.exc_info = None
        return True


@dataclass
class AgentRuntime:
    """Shared model and MCP connections with per-chat state."""

    model: ModelConfig
    client: AsyncOpenAI
    tool_schemas: list[dict[str, Any]]
    mcp_routes: dict[str, MCPRoute]
    histories: dict[tuple[int, int], list[dict[str, Any]]] = field(default_factory=dict)
    chat_locks: dict[tuple[int, int], asyncio.Lock] = field(default_factory=dict)
    pending_confirmations: dict[str, "PendingConfirmation"] = field(
        default_factory=dict
    )
    stack: AsyncExitStack | None = None
    chat_models: dict[
        tuple[int, int], tuple[str, ModelConfig, AsyncOpenAI]
    ] = field(default_factory=dict)
    extra_clients: list[AsyncOpenAI] = field(default_factory=list)


@dataclass
class PendingConfirmation:
    """A single tool approval waiting for its authorized Telegram user."""

    chat_id: int
    user_id: int
    future: asyncio.Future[bool]
    message_id: int


def parse_allowed_user_ids(value: str | None) -> frozenset[int]:
    """Parse a strict comma-separated list of Telegram user IDs."""
    if value is None or not value.strip():
        raise ValueError("TELEGRAM_ALLOWED_USER_IDS must contain at least one user ID")
    parts = value.split(",")
    if any(
        not part.strip().isascii() or not part.strip().isdecimal() for part in parts
    ):
        raise ValueError(
            "TELEGRAM_ALLOWED_USER_IDS must be comma-separated numeric IDs"
        )
    user_ids = [int(part.strip()) for part in parts]
    if any(user_id <= 0 for user_id in user_ids):
        raise ValueError("Telegram user IDs must be positive integers")
    if len(set(user_ids)) != len(user_ids):
        raise ValueError("TELEGRAM_ALLOWED_USER_IDS must not contain duplicates")
    return frozenset(user_ids)


def _trim_history(messages: list[dict[str, Any]]) -> None:
    """Keep the system prompt and the most recent complete user turns."""
    user_turns = [
        index for index, message in enumerate(messages) if message.get("role") == "user"
    ]
    if len(user_turns) <= MAX_HISTORY_TURNS:
        return
    first_kept_turn = user_turns[-MAX_HISTORY_TURNS]
    system_message = (
        messages[0] if messages and messages[0].get("role") == "system" else None
    )
    retained = messages[first_kept_turn:]
    messages[:] = ([system_message] if system_message is not None else []) + retained


def _split_message(text: str) -> list[str]:
    """Split a response into Telegram-safe chunks."""
    parts: list[str] = []
    current: list[str] = []
    current_size = 0
    for character in text:
        char_size = len(character.encode("utf-16-le")) // 2
        if current and current_size + char_size > MAX_TELEGRAM_MESSAGE_LENGTH:
            parts.append("".join(current))
            current = []
            current_size = 0
        current.append(character)
        current_size += char_size
    if current:
        parts.append("".join(current))
    return parts or ["(The assistant returned an empty response.)"]


async def _send_text(message: Any, text: str) -> None:
    for part in _split_message(text):
        await message.reply_text(part)


def _is_authorized(update: Update, allowed_user_ids: frozenset[int]) -> bool:
    user = update.effective_user
    return user is not None and user.id in allowed_user_ids


async def _request_confirmation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    tool_name: str,
    description: str,
) -> bool:
    """Wait for an authorized inline-button decision; timeout fails closed."""
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if message is None or user is None or chat is None:
        return False

    runtime: AgentRuntime = context.application.bot_data["agent_runtime"]
    nonce = secrets.token_urlsafe(12)
    future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
    prompt = await message.reply_text(
        f"Approve MCP action: {tool_name}\n"
        f"Operation: {description[:500]}\n"
        "This request expires in 60 seconds.",
        reply_markup=InlineKeyboardMarkup(
            [[
                InlineKeyboardButton("Approve", callback_data=f"mcp:{nonce}:y"),
                InlineKeyboardButton("Deny", callback_data=f"mcp:{nonce}:n"),
            ]]
        ),
    )
    runtime.pending_confirmations[nonce] = PendingConfirmation(
        chat_id=chat.id,
        user_id=user.id,
        future=future,
        message_id=prompt.message_id,
    )
    try:
        return await asyncio.wait_for(future, timeout=CONFIRMATION_TIMEOUT)
    except TimeoutError:
        try:
            await prompt.edit_text("Confirmation timed out; action denied.")
        except Exception as exc:
            logger.warning(
                "Could not update expired confirmation (%s)", type(exc).__name__
            )
        return False
    finally:
        runtime.pending_confirmations.pop(nonce, None)


async def _handle_confirmation(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if query is None:
        return
    allowed = context.application.bot_data["allowed_user_ids"]
    data = query.data or ""
    parts = data.split(":")
    if (
        len(parts) != 3
        or parts[0] != "mcp"
        or parts[2] not in {"y", "n"}
        or not _is_authorized(update, allowed)
    ):
        await query.answer("This confirmation is not available.", show_alert=True)
        return

    runtime: AgentRuntime = context.application.bot_data["agent_runtime"]
    pending = runtime.pending_confirmations.get(parts[1])
    chat = update.effective_chat
    user = update.effective_user
    if (
        pending is None
        or chat is None
        or user is None
        or query.message is None
        or pending.chat_id != chat.id
        or pending.user_id != user.id
        or pending.message_id != query.message.message_id
        or pending.future.done()
    ):
        await query.answer("This confirmation has expired or belongs to another chat.")
        return

    pending.future.set_result(parts[2] == "y")
    await query.answer("Decision recorded.")
    if query.message is not None:
        try:
            await query.message.edit_text(
                "Action approved." if parts[2] == "y" else "Action denied."
            )
        except Exception as exc:
            logger.warning(
                "Could not update confirmation message (%s)", type(exc).__name__
            )


async def _handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed = context.application.bot_data["allowed_user_ids"]
    if _is_authorized(update, allowed) and update.effective_message is not None:
        await update.effective_message.reply_text(
            "Harness agent ready. Send a message to chat; use /reset to clear "
            "this chat's history."
        )


async def _handle_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed = context.application.bot_data["allowed_user_ids"]
    if not _is_authorized(update, allowed):
        return
    user = update.effective_user
    chat = update.effective_chat
    message = update.effective_message
    if user is None or chat is None or message is None:
        return
    key = (chat.id, user.id)
    runtime: AgentRuntime = context.application.bot_data["agent_runtime"]
    lock = runtime.chat_locks.setdefault(key, asyncio.Lock())
    async with lock:
        runtime.histories.pop(key, None)
    await message.reply_text("Conversation history cleared.")


async def _handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed = context.application.bot_data["allowed_user_ids"]
    if not _is_authorized(update, allowed):
        return
    user = update.effective_user
    chat = update.effective_chat
    message = update.effective_message
    if user is None or chat is None or message is None or message.text is None:
        return
    if len(message.text) > MAX_INPUT_LENGTH:
        await message.reply_text(
            f"Message too long. Please keep messages under "
            f"{MAX_INPUT_LENGTH} characters."
        )
        return

    key = (chat.id, user.id)
    runtime: AgentRuntime = context.application.bot_data["agent_runtime"]
    lock = runtime.chat_locks.setdefault(key, asyncio.Lock())
    async with lock:
        history = runtime.histories.setdefault(key, [])
        model_name, model, client = runtime.chat_models.get(
            key, (
                next(
                    (
                        name for name, config in MODELS.items()
                        if config == runtime.model
                    ),
                    DEFAULT_MODEL,
                ),
                runtime.model,
                runtime.client,
            )
        )
        candidates = [model_name]
        while candidates:
            selected_model = candidates.pop(0)
            selected_config = MODELS[selected_model]
            if selected_model != model_name and selected_model.startswith("local"):
                try:
                    await asyncio.to_thread(
                        check_ollama_model,
                        selected_config.base_url,
                        selected_config.model,
                    )
                except RuntimeError as exc:
                    logger.warning("Skipping fallback model (%s)", type(exc).__name__)
                    continue
            if selected_model != model_name:
                model_name = selected_model
                model = selected_config
                client = AsyncOpenAI(
                    base_url=model.base_url, api_key=model.api_key
                )
                runtime.extra_clients.append(client)
                runtime.chat_models[key] = (model_name, model, client)
                logger.info("Switched chat to fallback model %s", model_name)
            try:
                answer = await run_agent(
                    message.text,
                    history,
                    client,
                    model,
                    runtime.tool_schemas,
                    runtime.mcp_routes,
                    load_memory(),
                    confirm_action=lambda tool, description: _request_confirmation(
                        update, context, tool, description
                    ),
                )
                runtime.chat_models[key] = (model_name, model, client)
                _trim_history(history)
                await _send_text(message, answer)
                return
            except APIStatusError as exc:
                fallbacks = fallback_models(model_name, exc.status_code)
                if fallbacks:
                    candidates = fallbacks
                    reason = (
                        "rejected the request size"
                        if exc.status_code == 413
                        else "reached its rate or usage limit"
                    )
                    logger.warning(
                        "%s %s; trying next model",
                        model_name,
                        reason,
                    )
                    continue
                error_text = (
                    "Sorry, the assistant couldn't complete that request. "
                    "Check the harness logs and try again."
                )
                logger.warning(
                    "Telegram agent request failed (HTTP %s)",
                    exc.status_code,
                    exc_info=True,
                )
                await message.reply_text(error_text)
                return
            except Exception as exc:
                logger.exception(
                    "Telegram agent request failed (%s)", type(exc).__name__
                )
                await message.reply_text(
                    "Sorry, the assistant couldn't complete that request. "
                    "Check the harness logs and try again."
                )
                return


async def _handle_error(
    _update: object, context: ContextTypes.DEFAULT_TYPE
) -> None:
    error = context.error
    logger.warning(
        "Telegram update failed (%s)", type(error).__name__ if error else "unknown"
    )


def _parse_mcp_selection(value: str | None) -> set[str] | None:
    if value is None:
        return None
    names = [name.strip() for name in value.split(",")]
    if any(not name for name in names) or len(names) != len(set(names)):
        raise ValueError("--mcp-servers requires unique comma-separated server names")
    return set(names)


def create_application(
    token: str,
    allowed_user_ids: frozenset[int],
    model_name: str = DEFAULT_MODEL,
    enable_mcp: bool = True,
    selected_mcp_servers: set[str] | None = None,
    mcp_startup_timeout: float = DEFAULT_STARTUP_TIMEOUT,
) -> Application:
    """Create Telegram handlers and initialize the agent runtime at startup."""
    if model_name not in MODELS:
        raise ValueError(
            f"Unknown model '{model_name}'. Available: {', '.join(MODELS)}"
        )
    model = MODELS[model_name]
    if not model_name.startswith("local") and not model.api_key.strip():
        required_key = required_api_key(model_name)
        raise ValueError(f"Model '{model_name}' requires {required_key}.")

    async def post_init(application: Application) -> None:
        if model_name.startswith("local"):
            await asyncio.to_thread(check_ollama_model, model.base_url, model.model)
        stack = AsyncExitStack()
        await stack.__aenter__()
        try:
            if enable_mcp:
                mcp_schemas, routes = await connect_mcp(
                    stack,
                    selected_servers=selected_mcp_servers,
                    startup_timeout=mcp_startup_timeout,
                )
            else:
                mcp_schemas, routes = [], {}
            client = AsyncOpenAI(base_url=model.base_url, api_key=model.api_key)
            application.bot_data["agent_runtime"] = AgentRuntime(
                model=model,
                client=client,
                tool_schemas=[*FILE_TOOL_SCHEMAS, MEMORY_TOOL, *mcp_schemas],
                mcp_routes=routes,
                stack=stack,
            )
        except Exception:
            await stack.aclose()
            raise

    async def post_shutdown(application: Application) -> None:
        runtime = application.bot_data.get("agent_runtime")
        if runtime is not None:
            try:
                clients = [runtime.client, *runtime.extra_clients]
                await asyncio.gather(*(client.close() for client in clients))
            finally:
                if runtime.stack is not None:
                    await runtime.stack.aclose()

    application = (
        Application.builder()
        .token(token)
        .concurrent_updates(16)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    application.bot_data["allowed_user_ids"] = allowed_user_ids
    application.add_handler(CommandHandler("start", _handle_start))
    application.add_handler(CommandHandler("help", _handle_start))
    application.add_handler(CommandHandler("reset", _handle_reset))
    application.add_handler(CallbackQueryHandler(_handle_confirmation))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_message)
    )
    application.add_error_handler(_handle_error)
    return application


async def _run_application(application: Application) -> None:
    """Run Telegram lifecycle hooks in one task so MCP contexts close safely."""
    if application.updater is None:
        raise RuntimeError("Telegram application has no updater")

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    handled_signals = (signal.SIGINT, signal.SIGTERM, signal.SIGABRT)
    registered_signals: list[signal.Signals] = []
    for handled_signal in handled_signals:
        try:
            loop.add_signal_handler(handled_signal, stop_event.set)
        except (NotImplementedError, RuntimeError):
            logger.debug("Signal handler unavailable for %s", handled_signal.name)
        else:
            registered_signals.append(handled_signal)

    try:
        await application.initialize()
        if application.post_init is not None:
            await application.post_init(application)

        def handle_polling_error(error: Exception) -> None:
            application.create_task(
                application.process_error(error=error, update=None)
            )

        await application.updater.start_polling(
            drop_pending_updates=True,
            error_callback=handle_polling_error,
        )
        await application.start()
        await stop_event.wait()
    finally:
        for handled_signal in registered_signals:
            try:
                loop.remove_signal_handler(handled_signal)
            except (NotImplementedError, RuntimeError) as exc:
                logger.warning(
                    "Could not remove signal handler for %s (%s)",
                    handled_signal.name,
                    type(exc).__name__,
                )

        async def cleanup(
            label: str, operation: Callable[[], Awaitable[None]]
        ) -> None:
            try:
                await operation()
            except Exception:
                logger.exception("Telegram %s cleanup failed", label)

        if application.updater.running:
            await cleanup("polling", application.updater.stop)
        application_was_running = application.running
        if application_was_running:
            await cleanup("application", application.stop)
            post_stop = application.post_stop
            if post_stop is not None:
                await cleanup("post-stop hook", lambda: post_stop(application))
        await cleanup("shutdown", application.shutdown)
        post_shutdown = application.post_shutdown
        if post_shutdown is not None:
            await cleanup(
                "post-shutdown hook",
                lambda: post_shutdown(application),
            )


def main() -> None:
    """Validate credentials and run the Telegram bot with long polling."""
    parser = argparse.ArgumentParser(
        description="Chat with the agent harness through a Telegram bot."
    )
    parser.add_argument("--model", choices=MODELS, default=DEFAULT_MODEL)
    parser.add_argument("--no-mcp", action="store_true")
    parser.add_argument("--mcp-servers", metavar="NAME,NAME")
    parser.add_argument(
        "--mcp-startup-timeout",
        type=float,
        default=os.environ.get(
            "AGENT_MCP_STARTUP_TIMEOUT", str(DEFAULT_STARTUP_TIMEOUT)
        ),
    )
    args = parser.parse_args()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        parser.error("TELEGRAM_BOT_TOKEN must be set")
    try:
        allowed_user_ids = parse_allowed_user_ids(
            os.environ.get("TELEGRAM_ALLOWED_USER_IDS")
        )
        selected_mcp_servers = _parse_mcp_selection(args.mcp_servers)
        if not math.isfinite(args.mcp_startup_timeout) or args.mcp_startup_timeout <= 0:
            raise ValueError("--mcp-startup-timeout must be a finite positive number")
        if args.no_mcp and selected_mcp_servers is not None:
            raise ValueError("--mcp-servers cannot be used together with --no-mcp")
        application = create_application(
            token,
            allowed_user_ids,
            model_name=args.model,
            enable_mcp=not args.no_mcp,
            selected_mcp_servers=selected_mcp_servers,
            mcp_startup_timeout=args.mcp_startup_timeout,
        )
    except ValueError as exc:
        parser.error(str(exc))

    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    redaction_filter = _TokenRedactionFilter(token)
    for handler in logging.getLogger().handlers:
        handler.addFilter(redaction_filter)
    try:
        asyncio.run(_run_application(application))
    except KeyboardInterrupt:
        print("\nGoodbye.")


if __name__ == "__main__":
    main()
