"use client";
import { useEffect, useRef, useState } from "react";
import type { ChatMessage } from "@/types";
import MessageBubble from "./MessageBubble";

interface Props {
  messages: ChatMessage[];
  busy: boolean;
  disabled: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
  onClear: () => void;
}

export default function ChatPanel({ messages, busy, disabled, onSend, onStop, onClear }: Props) {
  const [text, setText] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const submit = () => {
    const t = text.trim();
    if (!t || busy || disabled) return;
    onSend(t);
    setText("");
  };

  return (
    <section className="flex min-h-0 flex-1 flex-col">
      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {messages.length === 0 && (
          <p className="mt-20 text-center text-sm text-zinc-500">
            {disabled ? "Open Settings and connect to your local agent to start." : "Ask your agent something."}
          </p>
        )}
        {messages.map((m) => (
          <MessageBubble key={m.id} m={m} />
        ))}
        <div ref={endRef} />
      </div>
      <div className="border-t border-zinc-800 p-3">
        <div className="flex gap-2">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            rows={2}
            maxLength={8000}
            placeholder={disabled ? "Not connected" : "Message (Enter to send, Shift+Enter for newline)"}
            className="flex-1 resize-none rounded-lg border border-zinc-800 bg-zinc-900 p-2 text-sm outline-none focus:border-sky-600"
          />
          {busy ? (
            <button onClick={onStop} className="rounded-lg bg-red-600 px-4 text-sm hover:bg-red-500">Stop</button>
          ) : (
            <button onClick={submit} disabled={disabled || !text.trim()} className="rounded-lg bg-sky-600 px-4 text-sm hover:bg-sky-500 disabled:opacity-40">Send</button>
          )}
        </div>
        {messages.length > 0 && !busy && (
          <button onClick={onClear} className="mt-2 text-xs text-zinc-500 hover:text-zinc-300">Clear conversation</button>
        )}
      </div>
    </section>
  );
}
