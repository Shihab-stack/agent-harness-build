"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ChatPanel from "@/components/ChatPanel";
import SettingsModal from "@/components/SettingsModal";
import SkillsPanel from "@/components/SkillsPanel";
import StatusBadge from "@/components/StatusBadge";
import { ApiError, addSkill, getHealth, getSkills, resetChat, streamChat, toggleSkill } from "@/lib/api";
import type { ChatMessage, ConnectionConfig, ConnectionState, Diagnostic, Skill, StreamEvent } from "@/types";

const STORAGE_KEY = "harness.connection.v1";
const EMPTY: ConnectionConfig = { url: "", apiKey: "" };
const uid = () => crypto.randomUUID();

const toDiagnostic = (err: unknown): Diagnostic =>
  err instanceof ApiError
    ? err.diagnostic
    : { title: "Unexpected error", detail: err instanceof Error ? err.message : String(err), hints: [] };

export default function Page() {
  const [config, setConfig] = useState<ConnectionConfig>(EMPTY);
  const [conn, setConn] = useState<ConnectionState>({ status: "unconfigured" });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [skillError, setSkillError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const connect = useCallback(async (cfg: ConnectionConfig) => {
    if (!cfg.url || !cfg.apiKey) {
      setConn({ status: "unconfigured" });
      return;
    }
    setConn({ status: "checking" });
    try {
      const health = await getHealth(cfg);
      setConn({ status: "online", model: health.model, toolCount: health.toolCount });
      setSkills(await getSkills(cfg));
    } catch (err) {
      setSkills([]);
      setConn({ status: "error", diagnostic: toDiagnostic(err) });
    }
  }, []);

  // Load persisted config once on the client (localStorage is unavailable during SSR).
  useEffect(() => {
    let saved = EMPTY;
    try {
      saved = { ...EMPTY, ...JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}") };
    } catch {}
    setConfig(saved);
    if (saved.url && saved.apiKey) connect(saved);
    else setSettingsOpen(true);
  }, [connect]);

  const saveConfig = (cfg: ConnectionConfig) => {
    setConfig(cfg);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(cfg));
    } catch {}
    connect(cfg).then(() => setSettingsOpen((open) => open)); // keep modal open to show the result
  };

  const patchAssistant = (id: string, fn: (m: ChatMessage) => ChatMessage) =>
    setMessages((all) => all.map((m) => (m.id === id ? fn(m) : m)));

  const applyEvent = (id: string, e: StreamEvent) =>
    patchAssistant(id, (m) => {
      switch (e.type) {
        case "token":
          return { ...m, content: m.content + e.text };
        case "tool": {
          if (e.status === "running") return { ...m, tools: [...m.tools, { id: uid(), name: e.name, status: "running" }] };
          const idx = m.tools.map((t) => t.name === e.name && t.status === "running").lastIndexOf(true);
          if (idx === -1) return { ...m, tools: [...m.tools, { id: uid(), name: e.name, status: e.status }] };
          return { ...m, tools: m.tools.map((t, i) => (i === idx ? { ...t, status: e.status } : t)) };
        }
        case "error":
          return { ...m, state: "error", error: { title: "Agent error", detail: e.message, hints: ["Check the agent's terminal for the full traceback."] } };
        case "done":
          return { ...m, state: "done" };
      }
    });

  const send = async (text: string) => {
    const assistantId = uid();
    setMessages((all) => [
      ...all,
      { id: uid(), role: "user", content: text, tools: [], state: "done" },
      { id: assistantId, role: "assistant", content: "", tools: [], state: "streaming" },
    ]);
    const controller = new AbortController();
    abortRef.current = controller;
    setBusy(true);
    try {
      await streamChat(config, text, (e) => applyEvent(assistantId, e), controller.signal);
      patchAssistant(assistantId, (m) => (m.state === "streaming" ? { ...m, state: "done" } : m));
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        patchAssistant(assistantId, (m) => ({ ...m, state: "done" }));
      } else {
        const diagnostic = toDiagnostic(err);
        patchAssistant(assistantId, (m) => ({ ...m, state: "error", error: diagnostic }));
        setConn({ status: "error", diagnostic });
      }
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  };

  const clear = async () => {
    setMessages([]);
    try {
      await resetChat(config);
    } catch {} // local view is already cleared; server history resets on next success
  };

  const runSkillAction = async (action: () => Promise<Skill[]>) => {
    setSkillError(undefined);
    try {
      setSkills(await action());
    } catch (err) {
      const d = toDiagnostic(err);
      setSkillError(`${d.title}: ${d.detail}`);
      throw err;
    }
  };

  const online = conn.status === "online";

  return (
    <main className="flex h-screen flex-col">
      <header className="flex items-center justify-between border-b border-zinc-800 px-4 py-2">
        <h1 className="text-sm font-semibold">Agent Harness</h1>
        <div className="flex items-center gap-2">
          <StatusBadge state={conn} onClick={() => connect(config)} />
          <button onClick={() => setSettingsOpen(true)} className="rounded border border-zinc-800 px-3 py-1 text-xs hover:bg-zinc-900">
            Settings
          </button>
        </div>
      </header>

      {conn.status === "error" && !settingsOpen && (
        <div className="border-b border-red-900 bg-red-950/40 px-4 py-2 text-xs text-red-200">
          {conn.diagnostic.title}: {conn.diagnostic.detail}{" "}
          <button className="underline" onClick={() => setSettingsOpen(true)}>Details</button>
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        <ChatPanel messages={messages} busy={busy} disabled={!online} onSend={send} onStop={() => abortRef.current?.abort()} onClear={clear} />
        <SkillsPanel
          skills={skills}
          disabled={!online}
          error={skillError}
          onToggle={(name, enabled) => runSkillAction(() => toggleSkill(config, name, enabled)).catch(() => {})}
          onAdd={(body) => runSkillAction(() => addSkill(config, body)).catch(() => {})}
        />
      </div>

      <SettingsModal
        key={`${settingsOpen}`}
        open={settingsOpen}
        config={config}
        state={conn}
        onSave={saveConfig}
        onClose={() => setSettingsOpen(false)}
      />
    </main>
  );
}
