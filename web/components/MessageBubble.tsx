import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage } from "@/types";
import DiagnosticCard from "./DiagnosticCard";
import ToolLog from "./ToolLog";

export default function MessageBubble({ m }: { m: ChatMessage }) {
  if (m.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl bg-sky-600 px-4 py-2 text-sm">{m.content}</div>
      </div>
    );
  }
  return (
    <div className="max-w-[90%]">
      <ToolLog tools={m.tools} />
      {m.content && (
        <div className="md rounded-2xl bg-zinc-900 px-4 py-2 text-sm">
          {/* react-markdown does not render raw HTML by default, which keeps model output safe. */}
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
        </div>
      )}
      {m.state === "streaming" && (
        <p className="mt-1 animate-pulse text-xs text-zinc-500">{m.content ? "Writing…" : "Thinking…"}</p>
      )}
      {m.error && <DiagnosticCard d={m.error} />}
    </div>
  );
}
