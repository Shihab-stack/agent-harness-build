"""Tests for preflight checks of configured Ollama models."""

import io
import json
import unittest
from dataclasses import replace
from unittest.mock import patch

from agent_herness_build import models
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


class CloudModelSelectionTests(unittest.TestCase):
    def test_default_prefers_gemini_then_groq_then_local(self) -> None:
        gemini = replace(models.MODELS["gemini"], api_key="gemini")
        groq = replace(models.MODELS["groq"], api_key="groq")
        with patch.dict(models.MODELS, {"gemini": gemini, "groq": groq}):
            self.assertEqual(models.default_model(), "gemini")
        with patch.dict(
            models.MODELS,
            {"gemini": replace(gemini, api_key=""), "groq": groq},
        ):
            self.assertEqual(models.default_model(), "groq")
        with patch.dict(
            models.MODELS,
            {
                "gemini": replace(gemini, api_key=""),
                "groq": replace(groq, api_key=""),
            },
        ):
            self.assertEqual(models.default_model(), "local")

    def test_default_prefers_configured_groq_otherwise_local(self) -> None:
        groq = replace(models.MODELS["groq"], api_key="groq")
        with patch.dict(
            models.MODELS,
            {"gemini": replace(models.MODELS["gemini"], api_key=""), "groq": groq},
        ):
            self.assertEqual(models.default_model(), "groq")
        with patch.dict(
            models.MODELS,
            {
                "gemini": replace(models.MODELS["gemini"], api_key=""),
                "groq": replace(groq, api_key=""),
            },
        ):
            self.assertEqual(models.default_model(), "local")

    def test_groq_fallback_runs_after_rate_limit_or_oversized_request(self) -> None:
        groq = replace(models.MODELS["groq"], api_key="groq")
        with patch.dict(
            models.MODELS,
            {"gemini": replace(models.MODELS["gemini"], api_key=""), "groq": groq},
        ):
            self.assertEqual(
                models.fallback_models("groq", 429),
                ["local", "local-small"],
            )
            self.assertEqual(
                models.fallback_models("groq", 413),
                ["local", "local-small"],
            )
            self.assertEqual(models.fallback_models("groq", 401), [])

    def test_gemini_quota_fallback_uses_configured_groq_before_local(self) -> None:
        gemini = replace(models.MODELS["gemini"], api_key="gemini")
        groq = replace(models.MODELS["groq"], api_key="groq")
        with patch.dict(models.MODELS, {"gemini": gemini, "groq": groq}):
            self.assertEqual(
                models.fallback_models("gemini", 429),
                ["groq", "local", "local-small"],
            )

    def test_retired_github_inference_models_are_not_configured(self) -> None:
        self.assertNotIn("github-gpt4o", models.MODELS)
        self.assertNotIn("github-deepseek", models.MODELS)

    def test_free_cloud_models_have_output_token_caps(self) -> None:
        self.assertEqual(models.MODELS["groq"].max_output_tokens, 1024)
        self.assertEqual(models.MODELS["gemini"].max_output_tokens, 1024)

    def test_gemini_uses_google_openai_compatible_endpoint_and_api_key(self) -> None:
        self.assertEqual(
            models.MODELS["gemini"].base_url,
            "https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        self.assertEqual(models.required_api_key("gemini"), "GEMINI_API_KEY")


if __name__ == "__main__":
    unittest.main()
