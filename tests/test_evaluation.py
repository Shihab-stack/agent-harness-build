"""Offline checks for tool-use evaluation result classification."""

import asyncio
import unittest

from agent_herness_build.models import ModelConfig
from scripts.evaluate_tool_use import evaluate_confirmation_gate, was_tool_requested


class EvaluationClassificationTests(unittest.TestCase):
    def test_detects_requested_tool_in_assistant_history(self) -> None:
        messages = [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "function": {
                            "name": "mcp_eval_create_event",
                            "arguments": "{}",
                        }
                    }
                ],
            }
        ]
        self.assertTrue(was_tool_requested(messages, "mcp_eval_create_event"))
        self.assertFalse(was_tool_requested(messages, "mcp_eval_weather"))

    def test_missing_tool_request_is_not_misclassified_as_denial(self) -> None:
        messages = [{"role": "assistant", "content": ""}]
        self.assertFalse(was_tool_requested(messages, "mcp_eval_create_event"))

    def test_denied_confirmation_gate_is_tested_deterministically(self) -> None:
        model = ModelConfig("http://localhost:11434/v1", "ollama", "test")
        passed, details = asyncio.run(evaluate_confirmation_gate(model))
        self.assertTrue(passed, details)
        self.assertIn("server calls=[]", details)
        self.assertIn("denial recorded=True", details)


if __name__ == "__main__":
    unittest.main()
