import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agent Harness",
  description: "Web UI for a local AI agent / MCP harness",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
