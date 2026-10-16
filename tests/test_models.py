"""Tests for preflight checks of configured Ollama models."""

import io
import json
import unittest
from unittest.mock import patch

from agent_herness_build.models import check_ollama_model


class OllamaModelCheckTests(unittest.TestCase):
    def test_installed_model_is_accepted(self) -> None:
        response = io.BytesIO(
            json.dumps({"models": [{"name": "qwen3.5:4b"}]}).encode("utf-8")
        )
        with patch(
            "agent_herness_build.models.urlopen", return_value=response
        ) as urlopen:
            check_ollama_model("http://localhost:11434/v1", "qwen3.5:4b")
        urlopen.assert_called_once_with("http://localhost:11434/api/tags", timeout=5)

    def test_missing_model_has_pull_command_and_available_choices(self) -> None:
        response = io.BytesIO(
            json.dumps({"models": [{"name": "qwen3.5:4b"}]}).encode("utf-8")
        )
        with patch("agent_herness_build.models.urlopen", return_value=response):
            with self.assertRaisesRegex(
                RuntimeError, r"ollama pull qwen3.5:2b.*qwen3.5:4b"
            ):
                check_ollama_model("http://localhost:11434/v1", "qwen3.5:2b")

    def test_unreachable_ollama_has_startup_guidance(self) -> None:
        from urllib.error import URLError

        with patch(
            "agent_herness_build.models.urlopen", side_effect=URLError("offline")
        ):
            with self.assertRaisesRegex(RuntimeError, "Start Ollama"):
                check_ollama_model("http://localhost:11434/v1", "qwen3.5:4b")


if __name__ == "__main__":
    unittest.main()
