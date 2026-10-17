"""Model backend configuration for local Ollama and optional cloud providers."""

import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


@dataclass(frozen=True)
class ModelConfig:
    """Describe an OpenAI-compatible chat endpoint and model identifier."""

    base_url: str
    api_key: str
    model: str


MODELS = {
    "local": ModelConfig(
        base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        api_key="ollama",
        model=os.environ.get("OLLAMA_MODEL", "qwen3.5:4b"),
    ),
    "local-small": ModelConfig(
        base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        api_key="ollama",
        model=os.environ.get("OLLAMA_SMALL_MODEL", "qwen2.5-coder:3b"),
    ),
    # --- FREE CLOUD PROVIDERS (NO CREDIT CARD REQUIRED) ---
    "github-gpt4o": ModelConfig(
        base_url="https://models.inference.ai.azure.com",
        api_key=os.environ.get("GITHUB_TOKEN", ""),
        model="gpt-4o",
    ),
    "github-deepseek": ModelConfig(
        base_url="https://models.inference.ai.azure.com",
        api_key=os.environ.get("GITHUB_TOKEN", ""),
        model="DeepSeek-R1",
    ),
    "groq": ModelConfig(
        base_url="https://api.groq.com/openai/v1",
        api_key=os.environ.get("GROQ_API_KEY", ""),
        model=os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
    ),
    # -----------------------------------------------------
    "gpt": ModelConfig(
        base_url="https://api.openai.com/v1",
        api_key=os.environ.get("OPENAI_API_KEY", ""),
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
    ),
    "claude": ModelConfig(
        base_url=os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1/"),
        api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        model=os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022"),
    ),
}

# Change default from local to a free cloud model if desired
DEFAULT_MODEL = "github-gpt4o"


def check_ollama_model(base_url: str, model: str) -> None:
    """Raise an actionable error if Ollama is unreachable or lacks a model."""
    ollama_url = f"{base_url.rstrip('/').removesuffix('/v1')}/api/tags"
    try:
        with urlopen(ollama_url, timeout=5) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(
            f"Ollama model check failed with HTTP {exc.code} at {ollama_url}."
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(
            f"Could not reach Ollama at {ollama_url}. Start Ollama and try again."
        ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Ollama returned an invalid model-list response from {ollama_url}."
        ) from exc

    models = result.get("models") if isinstance(result, dict) else None
    if not isinstance(models, list):
        raise RuntimeError(f"Ollama returned an invalid model list from {ollama_url}.")
    installed: set[str] = set()
    for item in models:
        if isinstance(item, dict):
            name = item.get("name") or item.get("model")
            if isinstance(name, str):
                installed.add(name)
    if model not in installed:
        choices = ", ".join(sorted(name for name in installed if isinstance(name, str)))
        detail = f" Installed models: {choices}." if choices else ""
        raise RuntimeError(
            f"Ollama model '{model}' is not installed. Run `ollama pull {model}` "
            "or choose an installed model with "
            f"OLLAMA_MODEL/OLLAMA_SMALL_MODEL.{detail}"
        )
