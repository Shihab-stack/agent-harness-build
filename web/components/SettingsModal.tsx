"use client";
import { useState } from "react";
import type { ConnectionConfig, ConnectionState } from "@/types";
import DiagnosticCard from "./DiagnosticCard";

interface Props {
  open: boolean;
  config: ConnectionConfig;
  state: ConnectionState;
  onSave: (c: ConnectionConfig) => void;
  onClose: () => void;
}

export default function SettingsModal({ open, config, state, onSave, onClose }: Props) {
  const [url, setUrl] = useState(config.url);
  const [apiKey, setApiKey] = useState(config.apiKey);
  const [show, setShow] = useState(false);
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <div className="w-full max-w-md space-y-3 rounded-xl border border-zinc-800 bg-zinc-950 p-5" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-lg font-semibold">Connect to your agent</h2>
        <label className="block text-sm">
          <span className="text-zinc-400">Tunnel URL</span>
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://something.trycloudflare.com"
            className="mt-1 w-full rounded border border-zinc-800 bg-zinc-900 p-2 outline-none focus:border-sky-600" />
        </label>
        <label className="block text-sm">
          <span className="text-zinc-400">API key</span>
          <div className="mt-1 flex gap-2">
            <input type={show ? "text" : "password"} value={apiKey} onChange={(e) => setApiKey(e.target.value)}
              autoComplete="off" className="w-full rounded border border-zinc-800 bg-zinc-900 p-2 outline-none focus:border-sky-600" />
            <button type="button" onClick={() => setShow(!show)} className="rounded bg-zinc-800 px-2 text-xs">{show ? "Hide" : "Show"}</button>
          </div>
        </label>
        <p className="text-xs text-zinc-500">
          Stored in this browser&apos;s localStorage only and sent only to the URL above. Use a key you can rotate.
        </p>
        {state.status === "error" && <DiagnosticCard d={state.diagnostic} />}
        {state.status === "online" && <p className="text-sm text-emerald-400">Connected · {state.toolCount} tools</p>}
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="rounded px-3 py-1.5 text-sm text-zinc-400 hover:text-zinc-200">Close</button>
          <button onClick={() => onSave({ url: url.trim(), apiKey: apiKey.trim() })} disabled={!url.trim() || !apiKey.trim()}
            className="rounded bg-sky-600 px-3 py-1.5 text-sm hover:bg-sky-500 disabled:opacity-40">
            Save &amp; connect
          </button>
        </div>
      </div>
    </div>
  );
}
