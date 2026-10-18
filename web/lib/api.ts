import type { ConnectionConfig, Diagnostic, Skill, StreamEvent } from "@/types";

export class ApiError extends Error {
  constructor(public diagnostic: Diagnostic) {
    super(diagnostic.title);
  }
}

export const normalizeUrl = (raw: string): string => {
  const trimmed = raw.trim().replace(/\/+$/, "");
  return /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
};

const headers = (cfg: ConnectionConfig): HeadersInit => ({
  Authorization: `Bearer ${cfg.apiKey}`,
  "Content-Type": "application/json",
});

/** A browser cannot tell "offline" from "CORS blocked" on a failed fetch.
 *  A no-cors probe separates them: it resolves (opaque) if the host answered at all. */
async function diagnoseNetworkFailure(url: string): Promise<Diagnostic> {
  if (window.location.protocol === "https:" && url.startsWith("http://")) {
    return {
      title: "Blocked: mixed content",
      detail: "This page is HTTPS but the agent URL is plain HTTP.",
      hints: ["Use the https:// URL printed by cloudflared or ngrok."],
    };
  }
  try {
    await fetch(`${url}/api/health`, { mode: "no-cors", signal: AbortSignal.timeout(6000) });
    return {
      title: "CORS blocked",
      detail: "The tunnel answered, but the agent did not allow this site's origin.",
      hints: [
        `Set HARNESS_ALLOWED_ORIGINS=${window.location.origin} on the agent and restart it.`,
        "Multiple origins are comma-separated, with no trailing slash.",
      ],
    };
  } catch {
    return {
      title: "Agent unreachable",
      detail: "No response from the tunnel URL.",
      hints: [
        "Check that the web server and cloudflared are both running locally.",
        "Quick tunnels get a new URL on every restart; paste the new one.",
        "Check the URL for typos.",
      ],
    };
  }
}

function diagnoseStatus(status: number): Diagnostic {
  switch (status) {
    case 401:
    case 403:
      return { title: "Authentication failed", detail: `HTTP ${status}`, hints: ["The API key must match HARNESS_API_KEY on the agent."] };
    case 404:
      return { title: "Endpoint not found", detail: "HTTP 404", hints: ["Use the tunnel root URL, without /api.", "Confirm the agent runs the web server module."] };
    case 502:
    case 503:
    case 504:
    case 530:
      return { title: "Tunnel is up, agent is down", detail: `HTTP ${status}`, hints: ["Start the web server locally, then retry.", "Confirm cloudflared points at the right local port."] };
    default:
      return { title: "Unexpected response", detail: `HTTP ${status}`, hints: ["Check the agent's terminal output."] };
  }
}

async function request<T>(cfg: ConnectionConfig, path: string, init?: RequestInit): Promise<T> {
  const url = normalizeUrl(cfg.url);
  let res: Response;
  try {
    res = await fetch(`${url}${path}`, {
      ...init,
      headers: { ...headers(cfg), ...(init?.headers ?? {}) },
      signal: init?.signal ?? AbortSignal.timeout(15000),
    });
  } catch {
    throw new ApiError(await diagnoseNetworkFailure(url));
  }
  if (!res.ok) {
    let detail = "";
    try {
      detail = (await res.json()).error ?? "";
    } catch {}
    const d = diagnoseStatus(res.status);
    throw new ApiError(detail ? { ...d, detail: `${d.detail}: ${detail}` } : d);
  }
  return res.json() as Promise<T>;
}

const post = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

export const getHealth = (cfg: ConnectionConfig) =>
  request<{ ok: boolean; model: string; toolCount: number }>(cfg, "/api/health");
export const getSkills = (cfg: ConnectionConfig) =>
  request<{ skills: Skill[] }>(cfg, "/api/skills").then((r) => r.skills);
export const toggleSkill = (cfg: ConnectionConfig, name: string, enabled: boolean) =>
  request<{ skills: Skill[] }>(cfg, "/api/skills/toggle", post({ name, enabled })).then((r) => r.skills);
export const addSkill = (cfg: ConnectionConfig, body: { name?: string; url?: string; content?: string }) =>
  request<{ skills: Skill[] }>(cfg, "/api/skills/add", post(body)).then((r) => r.skills);
export const resetChat = (cfg: ConnectionConfig) => request<{ ok: boolean }>(cfg, "/api/reset", post({}));

/** POST + SSE over fetch (EventSource cannot send POST bodies or auth headers). */
export async function streamChat(
  cfg: ConnectionConfig,
  message: string,
  onEvent: (e: StreamEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const url = normalizeUrl(cfg.url);
  let res: Response;
  try {
    res = await fetch(`${url}/api/chat`, {
      method: "POST",
      headers: { ...headers(cfg), Accept: "text/event-stream" },
      body: JSON.stringify({ message }),
      signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(await diagnoseNetworkFailure(url));
  }
  if (!res.ok || !res.body) throw new ApiError(diagnoseStatus(res.status));

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    let boundary: number;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const data = block
        .split("\n")
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(5).trimStart())
        .join("\n");
      if (!data) continue; // ping/comment
      try {
        onEvent(JSON.parse(data) as StreamEvent);
      } catch {}
    }
  }
}
