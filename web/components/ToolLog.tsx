import type { ToolEvent } from "@/types";

const icon: Record<ToolEvent["status"], string> = {
  running: "⏳",
  completed: "✓",
  failed: "✗",
  denied: "⛔",
};

export default function ToolLog({ tools }: { tools: ToolEvent[] }) {
  if (!tools.length) return null;
  return (
    <details open className="mb-2 rounded-lg border border-zinc-800 bg-zinc-900/60 text-xs">
      <summary className="cursor-pointer px-3 py-1.5 text-zinc-400">Tool activity ({tools.length})</summary>
      <ul className="space-y-1 px-3 pb-2 font-mono">
        {tools.map((t) => (
          <li key={t.id} className={t.status === "failed" || t.status === "denied" ? "text-red-400" : "text-zinc-300"}>
            {icon[t.status]} {t.name} <span className="text-zinc-500">{t.status}</span>
          </li>
        ))}
      </ul>
    </details>
  );
}
