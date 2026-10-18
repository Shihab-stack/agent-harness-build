export interface ConnectionConfig {
  url: string;
  apiKey: string;
}

export type ConnectionState =
  | { status: "unconfigured" }
  | { status: "checking" }
  | { status: "online"; model: string; toolCount: number }
  | { status: "error"; diagnostic: Diagnostic };

export interface Diagnostic {
  title: string;
  detail: string;
  hints: string[];
}

export type ToolStatus = "running" | "completed" | "failed" | "denied";

export interface ToolEvent {
  id: string;
  name: string;
  status: ToolStatus;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  tools: ToolEvent[];
  state: "streaming" | "done" | "error";
  error?: Diagnostic;
}

export interface Skill {
  name: string;
  kind: "skill" | "mcp";
  description: string;
  enabled: boolean;
  toolCount?: number;
  toggleable: boolean;
}

/** Events sent by the backend over SSE (`event:` name equals `type`). */
export type StreamEvent =
  | { type: "token"; text: string }
  | { type: "tool"; name: string; status: ToolStatus }
  | { type: "done" }
  | { type: "error"; message: string };
