# Harness UI

Next.js (App Router) + Tailwind + TypeScript frontend for the local agent harness.
The browser talks **directly** to your machine through a Cloudflare tunnel, so the
Vercel deployment holds no secrets and no server code.

```
Browser (Vercel page) --HTTPS/SSE--> cloudflared tunnel --> 127.0.0.1:8787 (web_server.py) --> agent + MCP
```

## 1. Add the backend bridge (once)

The harness ships a CLI and Telegram bot but no HTTP server. Copy
`harness-backend/web_server.py` to `src/agent_herness_build/web_server.py` and apply
`agent_events.patch.md` to `agent.py`. Add `sse-starlette`, `starlette` and `uvicorn`
to `pyproject.toml` dependencies (they are already installed transitively via `mcp`,
but declare what you import), then `uv sync --no-editable`.

## 2. Run the agent

```sh
export HARNESS_API_KEY="$(openssl rand -hex 24)"      # keep this; you paste it into the UI
export HARNESS_ALLOWED_ORIGINS="https://YOUR-APP.vercel.app,http://localhost:3000"
uv run --no-editable python -m agent_herness_build.web_server
```

It binds to `127.0.0.1:8787` only. Non-read-only MCP tools are **denied** in web mode
(no interactive confirmation yet), so the agent cannot mutate anything through the UI.

## 3. Open the tunnel with cloudflared

Install: `brew install cloudflared` (macOS), `winget install Cloudflare.cloudflared`
(Windows), or the package for your Linux distro.

**Quick tunnel (no account; URL changes every restart):**

```sh
cloudflared tunnel --url http://127.0.0.1:8787
```

Copy the `https://<random>.trycloudflare.com` URL it prints.

**Stable URL (free Cloudflare account + a domain on Cloudflare):**

```sh
cloudflared tunnel login
cloudflared tunnel create harness
cloudflared tunnel route dns harness agent.example.com
cat > ~/.cloudflared/config.yml <<'YML'
tunnel: harness
credentials-file: /home/YOU/.cloudflared/<TUNNEL-ID>.json
ingress:
  - hostname: agent.example.com
    service: http://127.0.0.1:8787
  - service: http_status:404
YML
cloudflared tunnel run harness
```

ngrok works too: `ngrok http 8787`.

## 4. Deploy the UI to Vercel

Push this folder to GitHub (if it lives in a monorepo, set Vercel's **Root Directory**
to `harness-ui`), import it in Vercel, keep the Next.js defaults, deploy. No
environment variables are needed. Local dev: `npm install && npm run dev`.

## 5. Connect

Open the app, click **Settings**, paste the tunnel URL and `HARNESS_API_KEY`, then
**Save & connect**. Both persist in `localStorage`.

## API contract

| Route | Purpose |
|---|---|
| `GET /api/health` | `{ok, model, toolCount}` |
| `GET /api/skills` | behavioral skills (toggleable, one active at a time) + MCP servers (read-only) |
| `POST /api/skills/toggle` | `{name, enabled}` |
| `POST /api/skills/add` | `{url}` (https only) or `{name, content}`; no overwrite, 64 KiB cap |
| `POST /api/chat` | `{message}` -> SSE events `token`, `tool`, `done`, `error` |
| `POST /api/reset` | clear server-side history |

All routes require `Authorization: Bearer <HARNESS_API_KEY>`.

## Troubleshooting

| UI message | Meaning / fix |
|---|---|
| Agent unreachable | Server or cloudflared not running, or the quick-tunnel URL changed |
| CORS blocked | Add the exact origin (no trailing slash) to `HARNESS_ALLOWED_ORIGINS`, restart |
| Authentication failed | API key differs from `HARNESS_API_KEY` |
| Tunnel is up, agent is down (502/530) | cloudflared is running but nothing listens on the port |
| Mixed content | Use the `https://` tunnel URL, not `http://` |

## Security notes

- Anyone with the tunnel URL **and** the key controls your agent's file/MCP tools. Use a
  long random key, stop the tunnel when not in use, and rotate the key if shared.
- The key lives in this browser's localStorage, readable by any script on the page's
  origin. Dependencies here are minimal and `react-markdown` does not render raw HTML.
- Added skills are injected into the system prompt; only add ones you trust.
