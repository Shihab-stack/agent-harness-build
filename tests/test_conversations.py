"""Tests for safely saved conversation histories."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_herness_build import conversations


class ConversationTests(unittest.TestCase):
    def test_save_and_load_conversation(self) -> None:
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            conversations, "WORKSPACE", Path(temp_dir)
        ):
            self.assertEqual(
                conversations.save_conversation("daily-chat", messages),
                "saved conversation 'daily-chat'",
            )
            self.assertEqual(conversations.load_conversation("daily-chat"), messages)

    def test_invalid_names_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            conversations, "WORKSPACE", Path(temp_dir)
        ):
            with self.assertRaisesRegex(ValueError, "name must be"):
                conversations.save_conversation("../outside", [])

    def test_missing_and_malformed_conversations_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            conversations, "WORKSPACE", Path(temp_dir)
        ):
            with self.assertRaisesRegex(ValueError, "no saved conversation"):
                conversations.load_conversation("missing")
            path = conversations.conversation_path("broken")
            path.parent.mkdir(parents=True)
            path.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid format"):
                conversations.load_conversation("broken")


if __name__ == "__main__":
    unittest.main()
