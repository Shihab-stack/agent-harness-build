import type { Diagnostic } from "@/types";

export default function DiagnosticCard({ d, onRetry }: { d: Diagnostic; onRetry?: () => void }) {
  return (
    <div className="rounded-lg border border-red-900 bg-red-950/40 p-3 text-sm">
      <p className="font-medium text-red-300">{d.title}</p>
      <p className="text-red-200/80">{d.detail}</p>
      <ul className="mt-2 list-disc pl-5 text-zinc-300">
        {d.hints.map((h) => (
          <li key={h}>{h}</li>
        ))}
      </ul>
      {onRetry && (
        <button onClick={onRetry} className="mt-2 rounded bg-zinc-800 px-2 py-1 text-xs hover:bg-zinc-700">
          Retry
        </button>
      )}
    </div>
  );
}
