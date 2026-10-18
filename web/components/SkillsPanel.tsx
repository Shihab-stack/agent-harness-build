"use client";
import { useRef, useState } from "react";
import type { Skill } from "@/types";

interface Props {
  skills: Skill[];
  disabled: boolean;
  error?: string;
  onToggle: (name: string, enabled: boolean) => void;
  onAdd: (body: { name?: string; url?: string; content?: string }) => Promise<void>;
}

export default function SkillsPanel({ skills, disabled, error, onToggle, onAdd }: Props) {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const add = async (body: Parameters<Props["onAdd"]>[0]) => {
    setBusy(true);
    try {
      await onAdd(body);
      setUrl("");
    } finally {
      setBusy(false);
    }
  };

  const onFile = async (f?: File) => {
    if (!f) return;
    await add({ name: f.name.replace(/\.md$/i, "").toLowerCase(), content: await f.text() });
    if (fileRef.current) fileRef.current.value = "";
  };

  return (
    <aside className="flex w-72 shrink-0 flex-col border-l border-zinc-800">
      <h2 className="border-b border-zinc-800 px-4 py-3 text-sm font-semibold">Skills &amp; MCP</h2>
      <div className="flex-1 space-y-2 overflow-y-auto p-3">
        {skills.length === 0 && <p className="text-xs text-zinc-500">{disabled ? "Connect to load skills." : "No skills found."}</p>}
        {skills.map((s) => (
          <div key={`${s.kind}:${s.name}`} className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-2">
            <div className="flex items-center justify-between gap-2">
              <span className="truncate text-sm">{s.name}</span>
              <input type="checkbox" checked={s.enabled} disabled={!s.toggleable || disabled}
                title={s.toggleable ? "Toggle" : "MCP servers change via --mcp-servers and a restart"}
                onChange={(e) => onToggle(s.name, e.target.checked)} />
            </div>
            <p className="text-[11px] text-zinc-500">
              {s.kind === "mcp" ? `MCP · ${s.toolCount ?? 0} tools` : "Behavioral skill"}
            </p>
            {s.description && <p className="mt-1 line-clamp-2 text-xs text-zinc-400">{s.description}</p>}
          </div>
        ))}
      </div>
      <div className="space-y-2 border-t border-zinc-800 p-3">
        <p className="text-xs text-zinc-400">Add a skill (Markdown)</p>
        <div className="flex gap-1">
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…/skill.md" disabled={disabled}
            className="min-w-0 flex-1 rounded border border-zinc-800 bg-zinc-900 p-1.5 text-xs outline-none" />
          <button disabled={disabled || busy || !url.trim()} onClick={() => add({ url: url.trim() })}
            className="rounded bg-zinc-800 px-2 text-xs disabled:opacity-40">Add</button>
        </div>
        <input ref={fileRef} type="file" accept=".md,text/markdown,text/plain" disabled={disabled || busy}
          onChange={(e) => onFile(e.target.files?.[0])} className="w-full text-xs text-zinc-400" />
        {error && <p className="text-xs text-red-400">{error}</p>}
        <p className="text-[11px] text-zinc-600">Skills become system-prompt instructions. Only add ones you trust.</p>
      </div>
    </aside>
  );
}
