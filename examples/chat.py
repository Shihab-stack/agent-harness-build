"""Minimal example that chats directly with a locally running Ollama model."""

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


OLLAMA_URL = "http://localhost:11434"


class OllamaError(RuntimeError):
    """Raised when the Ollama API cannot provide a chat response."""


def chat(model: str, messages: list[dict[str, str]]) -> str:
    """Send a non-streaming chat request and return its assistant text."""
    payload = json.dumps(
        {"model": model, "messages": messages, "stream": False}
    ).encode("utf-8")
    request = Request(
        f"{OLLAMA_URL}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=120) as response:
            result: Any = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise OllamaError(f"Ollama returned HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise OllamaError(
            "Could not reach Ollama at "
            f"{OLLAMA_URL}. Make sure Ollama is running. ({exc})"
        ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OllamaError("Ollama returned an invalid JSON response.") from exc

    message = result.get("message") if isinstance(result, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise OllamaError("Ollama's response did not contain message content.")
    return content
