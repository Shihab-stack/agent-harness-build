"""HTTP + SSE bridge exposing the agent harness to the web UI.

Place at src/agent_herness_build/web_server.py. Run:
    HARNESS_API_KEY=... HARNESS_ALLOWED_ORIGINS=https://your-app.vercel.app \
        uv run --no-editable python -m agent_herness_build.web_server
Binds to 127.0.0.1 only; expose it through a tunnel, never directly.
"""

import asyncio
import json
import os
import secrets
import urllib.request
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import uvicorn
from openai import AsyncOpenAI
from sse_starlette.sse import EventSourceResponse
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from agent_herness_build.agent import run_agent
from agent_herness_build.mcp import connect_mcp, load_server_config
from agent_herness_build.models import DEFAULT_MODEL, MODELS, check_ollama_model
from agent_herness_build.skills import SKILL_NAME, SKILLS_DIR, list_skills
from agent_herness_build.tools.files import FILE_TOOL_SCHEMAS
from agent_herness_build.tools.memory import MEMORY_TOOL, load_memory

MAX_MESSAGE = 8_000
MAX_SKILL_BYTES = 64 * 1024
API_KEY = os.environ.get("HARNESS_API_KEY", "")


@dataclass
class State:
    model_name: str = DEFAULT_MODEL
    client: AsyncOpenAI | None = None
    schemas: list[dict[str, Any]] = field(default_factory=list)
    routes: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    active_skill: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


state = State()


def _error(message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _unauthorized(request: Request) -> JSONResponse | None:
    header = request.headers.get("authorization", "")
    token = header.removeprefix("Bearer ").strip()
    if not API_KEY or not secrets.compare_digest(token.encode(), API_KEY.encode()):
        return _error("invalid or missing API key", 401)
    return None


def _skill_list() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for name in list_skills():
        first = (SKILLS_DIR / f"{name}.md").read_text(encoding="utf-8").strip().splitlines()
        items.append({
            "name": name, "kind": "skill", "toggleable": True,
            "enabled": state.active_skill == name,
            "description": first[2] if len(first) > 2 else (first[0] if first else ""),
        })
    configured = sorted(load_server_config(), key=len, reverse=True)
    counts: dict[str, int] = {}
    for tool_name in state.routes:
        server = next((s for s in configured if tool_name.startswith(f"mcp_{s}_")), None)
        if server:
            counts[server] = counts.get(server, 0) + 1
    for server in sorted(load_server_config()):
        items.append({
            "name": server, "kind": "mcp", "toggleable": False,
            "enabled": server in counts, "toolCount": counts.get(server, 0),
            "description": "" if server in counts else "Not loaded (failed or not selected)",
        })
    return items


async def health(request: Request) -> JSONResponse:
    if (denied := _unauthorized(request)):
        return denied
    return JSONResponse({"ok": True, "model": MODELS[state.model_name].model, "toolCount": len(state.schemas)})


async def skills(request: Request) -> JSONResponse:
    if (denied := _unauthorized(request)):
        return denied
    return JSONResponse({"skills": _skill_list()})


async def toggle_skill(request: Request) -> JSONResponse:
    if (denied := _unauthorized(request)):
        return denied
    body = await request.json()
    name, enabled = body.get("name"), body.get("enabled")
    if name not in list_skills():
        return _error("MCP servers cannot be toggled at runtime; use --mcp-servers and restart", 409)
    state.active_skill = name if enabled else (None if state.active_skill == name else state.active_skill)
    return JSONResponse({"skills": _skill_list()})


async def add_skill(request: Request) -> JSONResponse:
    if (denied := _unauthorized(request)):
        return denied
    body = await request.json()
    name, content, url = body.get("name"), body.get("content"), body.get("url")
    if url:
        if not isinstance(url, str) or not url.startswith("https://"):
            return _error("skill URL must start with https://", 400)
        try:
            def fetch() -> bytes:
                with urllib.request.urlopen(url, timeout=10) as r:  # noqa: S310 - https enforced above
                    return r.read(MAX_SKILL_BYTES + 1)
            raw = await asyncio.to_thread(fetch)
            content = raw.decode("utf-8")
        except Exception as exc:
            return _error(f"could not fetch skill: {type(exc).__name__}", 400)
        name = name or url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".md").lower()
    if not isinstance(content, str) or not content.strip():
        return _error("skill content is empty", 400)
    if len(content.encode()) > MAX_SKILL_BYTES:
        return _error("skill exceeds 64 KiB", 400)
    if not isinstance(name, str) or not SKILL_NAME.fullmatch(name):
        return _error("skill name must be lowercase letters, digits and hyphens", 400)
    path = SKILLS_DIR / f"{name}.md"
    if path.exists():
        return _error(f"skill '{name}' already exists", 409)
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return JSONResponse({"skills": _skill_list()})


async def reset(request: Request) -> JSONResponse:
    if (denied := _unauthorized(request)):
        return denied
    async with state.lock:
        state.history.clear()
    return JSONResponse({"ok": True})


async def chat(request: Request):
    if (denied := _unauthorized(request)):
        return denied
    body = await request.json()
    prompt = str(body.get("message", "")).strip()
    if not prompt or len(prompt) > MAX_MESSAGE:
        return _error(f"message must be 1-{MAX_MESSAGE} characters", 400)

    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def work() -> None:
        async with state.lock:
            try:
                await run_agent(
                    prompt, state.history, state.client, MODELS[state.model_name],
                    state.schemas, state.routes, load_memory(),
                    on_token=lambda t: queue.put_nowait({"type": "token", "text": t}),
                    active_skill=state.active_skill,
                    on_event=queue.put_nowait,
                    # No confirm_action: MCP tools that are not read-only are denied (fail closed).
                )
                queue.put_nowait({"type": "done"})
            except Exception as exc:
                queue.put_nowait({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
            finally:
                queue.put_nowait(None)

    task = asyncio.create_task(work())

    async def events():
        try:
            while (event := await queue.get()) is not None:
                yield {"event": event["type"], "data": json.dumps(event)}
        finally:
            if not task.done():
                task.cancel()  # client disconnected or pressed Stop

    return EventSourceResponse(events(), ping=15)


@asynccontextmanager
async def lifespan(_app: Starlette):
    model = MODELS[state.model_name]
    if state.model_name.startswith("local"):
        await asyncio.to_thread(check_ollama_model, model.base_url, model.model)
    async with AsyncExitStack() as stack:
        mcp_schemas, state.routes = await connect_mcp(stack)
        state.schemas = [*FILE_TOOL_SCHEMAS, MEMORY_TOOL, *mcp_schemas]
        state.client = AsyncOpenAI(base_url=model.base_url, api_key=model.api_key)
        try:
            yield
        finally:
            await state.client.close()


def create_app() -> Starlette:
    if not API_KEY or len(API_KEY) < 16:
        raise SystemExit("Set HARNESS_API_KEY to a random string of at least 16 characters.")
    origins = [o.strip() for o in os.environ.get("HARNESS_ALLOWED_ORIGINS", "").split(",") if o.strip()]
    return Starlette(
        routes=[
            Route("/api/health", health),
            Route("/api/skills", skills),
            Route("/api/skills/toggle", toggle_skill, methods=["POST"]),
            Route("/api/skills/add", add_skill, methods=["POST"]),
            Route("/api/reset", reset, methods=["POST"]),
            Route("/api/chat", chat, methods=["POST"]),
        ],
        middleware=[Middleware(
            CORSMiddleware, allow_origins=origins,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
        )],
        lifespan=lifespan,
    )


def main() -> None:
    uvicorn.run(create_app(), host="127.0.0.1", port=int(os.environ.get("HARNESS_PORT", "8787")))


if __name__ == "__main__":
    main()
