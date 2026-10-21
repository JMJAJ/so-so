import { createFileRoute } from "@tanstack/react-router";

import { ChatProvider } from "@/features/chat/chat-context";
import AppShell from "@/features/shell/AppShell";
import { LoginGate } from "@/features/shell/LoginGate";
import { NavProvider } from "@/lib/nav";

export const Route = createFileRoute("/")({
  ssr: false,
  head: () => ({
    meta: [
      { title: "NEXUS // Evidence-based investment research" },
      {
        name: "description",
        content:
          "AI investment research grounded in market history, news history and event studies, verified with paper trading.",
      },
    ],
  }),
  component: Terminal,
});

function Terminal() {
  return (
    <LoginGate>
      <NavProvider>
        <ChatProvider>
          <AppShell />
        </ChatProvider>
      </NavProvider>
    </LoginGate>
  );
}
