import type { ConnectionState } from "@/types";

const styles: Record<ConnectionState["status"], { dot: string; label: string }> = {
  unconfigured: { dot: "bg-zinc-500", label: "Not connected" },
  checking: { dot: "bg-amber-400 animate-pulse", label: "Connecting…" },
  online: { dot: "bg-emerald-400", label: "Online" },
  error: { dot: "bg-red-500", label: "Offline" },
};

export default function StatusBadge({ state, onClick }: { state: ConnectionState; onClick?: () => void }) {
  const s = styles[state.status];
  return (
    <button onClick={onClick} className="flex items-center gap-2 rounded-full border border-zinc-800 px-3 py-1 text-xs hover:bg-zinc-900">
      <span className={`h-2 w-2 rounded-full ${s.dot}`} />
      {s.label}
      {state.status === "online" && <span className="text-zinc-500">· {state.model}</span>}
    </button>
  );
}
