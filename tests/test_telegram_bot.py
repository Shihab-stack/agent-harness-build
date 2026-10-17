"""Offline tests for the Telegram agent interface."""

import asyncio
import logging
import signal
import unittest
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from typing import AsyncIterator, Callable
from unittest.mock import AsyncMock, patch

import httpx2
from openai import APIStatusError
from agent_herness_build import telegram_bot
from agent_herness_build.models import MODELS


class TelegramBotTests(unittest.TestCase):
    def test_shutdown_closes_lifespan_resources_in_the_opening_task(self) -> None:
        async def run() -> None:
            loop = asyncio.get_running_loop()
            signal_handlers: dict[signal.Signals, Callable[[], None]] = {}
            entered_tasks: list[asyncio.Task | None] = []
            exited_tasks: list[asyncio.Task | None] = []

            resource_stack = AsyncExitStack()

            @asynccontextmanager
            async def resource() -> AsyncIterator[None]:
                entered_tasks.append(asyncio.current_task())
                try:
                    yield
                finally:
                    exited_tasks.append(asyncio.current_task())

            async def post_init(_application: object) -> None:
                await resource_stack.enter_async_context(resource())

            async def post_shutdown(_application: object) -> None:
                await resource_stack.aclose()

            async def initialize() -> None:
                return None

            async def start() -> None:
                application.running = True
                signal_handlers[signal.SIGINT]()

            async def stop() -> None:
                application.running = False

            async def shutdown() -> None:
                return None

            async def start_polling(**_kwargs: object) -> None:
                updater.running = True

            async def stop_polling() -> None:
                updater.running = False

            updater = SimpleNamespace(
                running=False,
                start_polling=start_polling,
                stop=stop_polling,
            )
            application = SimpleNamespace(
                updater=updater,
                initialize=initialize,
                post_init=post_init,
                start=start,
                running=False,
                stop=stop,
                post_stop=None,
                shutdown=shutdown,
                post_shutdown=post_shutdown,
            )

            def add_signal_handler(
                handled_signal: signal.Signals, callback: Callable[[], None]
            ) -> None:
                signal_handlers[handled_signal] = callback

            def remove_signal_handler(handled_signal: signal.Signals) -> bool:
                signal_handlers.pop(handled_signal, None)
                return True

            with (
                patch.object(
                    loop,
                    "add_signal_handler",
                    side_effect=add_signal_handler,
                ),
                patch.object(
                    loop, "remove_signal_handler", side_effect=remove_signal_handler
                ),
            ):
                await telegram_bot._run_application(application)

            self.assertEqual(len(entered_tasks), 1)
            self.assertEqual(entered_tasks, exited_tasks)
            self.assertFalse(updater.running)
            self.assertFalse(application.running)

        asyncio.run(run())

    def test_dependency_log_filter_redacts_bot_token(self) -> None:
        record = logging.LogRecord(
            "telegram",
            logging.ERROR,
            __file__,
            1,
            "request failed: %s",
            ("secret-token",),
            None,
        )
        self.assertTrue(
            telegram_bot._TokenRedactionFilter("secret-token").filter(record)
        )
        self.assertEqual(record.getMessage(), "request failed: [redacted]")

    def test_allowed_user_ids_require_a_nonempty_valid_allowlist(self) -> None:
        self.assertEqual(
            telegram_bot.parse_allowed_user_ids("123, 456"), frozenset({123, 456})
        )
        for value in (None, "", "123,nope", "0", "123,123"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                telegram_bot.parse_allowed_user_ids(value)

    def test_unauthorized_sender_is_silently_ignored(self) -> None:
        message = SimpleNamespace(text="hello", reply_text=AsyncMock())
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=22),
            effective_chat=SimpleNamespace(id=7),
            effective_message=message,
        )
        context = SimpleNamespace(
            application=SimpleNamespace(
                bot_data={"allowed_user_ids": frozenset({11})}
            )
        )
        with patch.object(
            telegram_bot, "run_agent", new_callable=AsyncMock
        ) as run_agent:
            asyncio.run(telegram_bot._handle_message(update, context))
        run_agent.assert_not_awaited()
        message.reply_text.assert_not_awaited()

    def test_conversations_are_separate_per_chat_and_user(self) -> None:
        async def run() -> None:
            runtime = telegram_bot.AgentRuntime(
                model=SimpleNamespace(),
                client=SimpleNamespace(),
                tool_schemas=[],
                mcp_routes={},
            )
            context = SimpleNamespace(
                application=SimpleNamespace(
                    bot_data={
                        "allowed_user_ids": frozenset({11, 22}),
                        "agent_runtime": runtime,
                    }
                )
            )
            with (
                patch.object(
                    telegram_bot, "load_memory", return_value=""
                ),
                patch.object(
                    telegram_bot,
                    "run_agent",
                    new_callable=AsyncMock,
                    return_value="reply",
                ) as run_agent,
            ):
                for chat_id, user_id in ((100, 11), (200, 22)):
                    message = SimpleNamespace(
                        text=f"message-{chat_id}", reply_text=AsyncMock()
                    )
                    update = SimpleNamespace(
                        effective_user=SimpleNamespace(id=user_id),
                        effective_chat=SimpleNamespace(id=chat_id),
                        effective_message=message,
                    )
                    await telegram_bot._handle_message(update, context)

            self.assertEqual(set(runtime.histories), {(100, 11), (200, 22)})
            self.assertEqual(run_agent.await_count, 2)
            self.assertIsNot(
                run_agent.await_args_list[0].args[1],
                run_agent.await_args_list[1].args[1],
            )

        asyncio.run(run())

    def test_rate_limit_switches_chat_to_configured_fallback(self) -> None:
        async def run() -> None:
            groq = replace(MODELS["groq"], api_key="groq")
            request = httpx2.Request(
                "POST", "https://api.groq.com/openai/v1/chat/completions"
            )
            error = APIStatusError(
                "rate limited",
                response=httpx2.Response(429, request=request),
                body=None,
            )
            runtime = telegram_bot.AgentRuntime(
                model=groq,
                client=SimpleNamespace(),
                tool_schemas=[],
                mcp_routes={},
            )
            message = SimpleNamespace(text="hello", reply_text=AsyncMock())
            update = SimpleNamespace(
                effective_user=SimpleNamespace(id=11),
                effective_chat=SimpleNamespace(id=100),
                effective_message=message,
            )
            context = SimpleNamespace(
                application=SimpleNamespace(
                    bot_data={
                        "allowed_user_ids": frozenset({11}),
                        "agent_runtime": runtime,
                    }
                )
            )
            fallback_client = SimpleNamespace()
            with (
                patch.dict(MODELS, {"groq": groq}),
                patch.object(telegram_bot, "check_ollama_model"),
                patch.object(
                    telegram_bot,
                    "run_agent",
                    new_callable=AsyncMock,
                    side_effect=[error, "fallback reply"],
                ) as run_agent,
                patch.object(telegram_bot, "AsyncOpenAI", return_value=fallback_client),
                patch.object(telegram_bot, "load_memory", return_value=""),
            ):
                await telegram_bot._handle_message(update, context)

            self.assertEqual(run_agent.await_count, 2)
            self.assertIs(run_agent.await_args_list[1].args[2], fallback_client)
            self.assertEqual(runtime.chat_models[(100, 11)][0], "local")
            message.reply_text.assert_awaited_once_with("fallback reply")

        asyncio.run(run())

    def test_agent_failure_logs_exception_details(self) -> None:
        async def run() -> None:
            runtime = telegram_bot.AgentRuntime(
                model=MODELS["groq"],
                client=SimpleNamespace(),
                tool_schemas=[],
                mcp_routes={},
            )
            message = SimpleNamespace(text="hello", reply_text=AsyncMock())
            update = SimpleNamespace(
                effective_user=SimpleNamespace(id=11),
                effective_chat=SimpleNamespace(id=100),
                effective_message=message,
            )
            context = SimpleNamespace(
                application=SimpleNamespace(
                    bot_data={
                        "allowed_user_ids": frozenset({11}),
                        "agent_runtime": runtime,
                    }
                )
            )
            with (
                patch.object(
                    telegram_bot,
                    "run_agent",
                    new_callable=AsyncMock,
                    side_effect=RuntimeError("Agent exceeded the tool-round limit"),
                ),
                patch.object(telegram_bot, "load_memory", return_value=""),
                self.assertLogs(telegram_bot.logger, level="ERROR") as captured,
            ):
                await telegram_bot._handle_message(update, context)

            self.assertIn("Agent exceeded the tool-round limit", captured.output[0])
            message.reply_text.assert_awaited_once()

        asyncio.run(run())

    def test_oversized_messages_are_rejected_without_running_agent(self) -> None:
        message = SimpleNamespace(
            text="x" * (telegram_bot.MAX_INPUT_LENGTH + 1),
            reply_text=AsyncMock(),
        )
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=11),
            effective_chat=SimpleNamespace(id=100),
            effective_message=message,
        )
        context = SimpleNamespace(
            application=SimpleNamespace(
                bot_data={"allowed_user_ids": frozenset({11})}
            )
        )
        with patch.object(
            telegram_bot, "run_agent", new_callable=AsyncMock
        ) as run_agent:
            asyncio.run(telegram_bot._handle_message(update, context))
        run_agent.assert_not_awaited()
        message.reply_text.assert_awaited_once()
        self.assertIn("too long", message.reply_text.await_args.args[0])

    def test_long_responses_split_to_telegram_utf16_limit(self) -> None:
        parts = telegram_bot._split_message("😀" * 3_000)
        self.assertGreater(len(parts), 1)
        self.assertTrue(
            all(len(part.encode("utf-16-le")) // 2 <= 4_096 for part in parts)
        )
        self.assertEqual("".join(parts), "😀" * 3_000)

    def test_history_limit_preserves_system_prompt_and_recent_turns(self) -> None:
        messages = [{"role": "system", "content": "system"}]
        for index in range(telegram_bot.MAX_HISTORY_TURNS + 2):
            messages.extend(
                [
                    {"role": "user", "content": f"user-{index}"},
                    {"role": "assistant", "content": f"assistant-{index}"},
                ]
            )
        telegram_bot._trim_history(messages)
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(
            [message["content"] for message in messages if message["role"] == "user"],
            [f"user-{index}" for index in range(2, telegram_bot.MAX_HISTORY_TURNS + 2)],
        )

    def test_updates_process_confirmation_callbacks_concurrently(self) -> None:
        application = telegram_bot.create_application(
            "123456:TEST_TOKEN",
            frozenset({11}),
            enable_mcp=False,
        )
        self.assertEqual(application.update_processor.max_concurrent_updates, 16)
        self.assertEqual(application.bot_data["allowed_user_ids"], frozenset({11}))

    def test_confirmation_requires_the_requesting_authorized_user(self) -> None:
        async def run() -> None:
            runtime = telegram_bot.AgentRuntime(
                model=SimpleNamespace(),
                client=SimpleNamespace(),
                tool_schemas=[],
                mcp_routes={},
            )
            source_message = SimpleNamespace(
                message_id=5,
                reply_text=AsyncMock(
                    return_value=SimpleNamespace(message_id=6, edit_text=AsyncMock())
                ),
            )
            request_update = SimpleNamespace(
                effective_user=SimpleNamespace(id=11),
                effective_chat=SimpleNamespace(id=100),
                effective_message=source_message,
            )
            context = SimpleNamespace(
                application=SimpleNamespace(
                    bot_data={
                        "allowed_user_ids": frozenset({11, 22}),
                        "agent_runtime": runtime,
                    }
                )
            )
            confirmation = asyncio.create_task(
                telegram_bot._request_confirmation(
                    request_update, context, "mcp_calendar_create", "Create event"
                )
            )
            await asyncio.sleep(0)
            self.assertEqual(len(runtime.pending_confirmations), 1)
            nonce = next(iter(runtime.pending_confirmations))

            def callback(user_id: int) -> SimpleNamespace:
                query = SimpleNamespace(
                    data=f"mcp:{nonce}:y",
                    answer=AsyncMock(),
                    message=SimpleNamespace(message_id=6, edit_text=AsyncMock()),
                )
                return SimpleNamespace(
                    callback_query=query,
                    effective_user=SimpleNamespace(id=user_id),
                    effective_chat=SimpleNamespace(id=100),
                )

            unauthorized_callback = callback(22)
            await telegram_bot._handle_confirmation(unauthorized_callback, context)
            self.assertFalse(confirmation.done())
            unauthorized_callback.callback_query.answer.assert_awaited_once()

            authorized_callback = callback(11)
            await telegram_bot._handle_confirmation(authorized_callback, context)
            self.assertTrue(await confirmation)
            edit_text = authorized_callback.callback_query.message.edit_text
            edit_text.assert_awaited_once_with("Action approved.")
            self.assertEqual(runtime.pending_confirmations, {})

        asyncio.run(run())

    def test_confirmation_times_out_as_denied(self) -> None:
        async def run() -> None:
            runtime = telegram_bot.AgentRuntime(
                model=SimpleNamespace(),
                client=SimpleNamespace(),
                tool_schemas=[],
                mcp_routes={},
            )
            prompt = SimpleNamespace(message_id=6, edit_text=AsyncMock())
            message = SimpleNamespace(reply_text=AsyncMock(return_value=prompt))
            update = SimpleNamespace(
                effective_user=SimpleNamespace(id=11),
                effective_chat=SimpleNamespace(id=100),
                effective_message=message,
            )
            context = SimpleNamespace(
                application=SimpleNamespace(
                    bot_data={"agent_runtime": runtime}
                )
            )
            with patch.object(telegram_bot, "CONFIRMATION_TIMEOUT", 0.001):
                result = await telegram_bot._request_confirmation(
                    update, context, "mcp_calendar_create", "Create event"
                )
            self.assertFalse(result)
            prompt.edit_text.assert_awaited_once_with(
                "Confirmation timed out; action denied."
            )
            self.assertEqual(runtime.pending_confirmations, {})

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
