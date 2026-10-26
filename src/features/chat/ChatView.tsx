import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { ago } from "@/lib/format";
import { cn } from "@/lib/utils";

import { ChatPanel } from "./ChatPanel";
import { ConversationControls } from "./ChatDrawer";
import { useChat } from "./chat-context";

/** Full-page chat: same conversation state as the drawer, with a history list. */
export default function ChatView() {
  const { conversationId, load, busy } = useChat();
  const conversations = useQuery({ queryKey: ["conversations"], queryFn: api.conversations });

  return (
    <div className="terminal-panel -my-1 flex h-[calc(100vh-7rem)] min-h-[480px]">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-border lg:flex">
        <div className="border-b border-border px-3 py-2.5 text-xs font-bold text-foreground">
          Conversations
        </div>
        <ul className="min-h-0 flex-1 overflow-y-auto py-1">
          {(conversations.data ?? []).map((conv) => (
            <li key={conv.id}>
              <button
                disabled={busy}
                onClick={() => void load(conv.id)}
                className={cn(
                  "w-full px-3 py-2 text-left text-[11px] hover:bg-accent/40",
                  conv.id === conversationId && "bg-accent text-foreground",
                )}
              >
                <div className="truncate">{conv.title}</div>
                <div className="text-[11px] text-muted-foreground">{ago(conv.updated_at)}</div>
              </button>
            </li>
          ))}
        </ul>
      </aside>
      <section className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b border-border px-3 py-2.5">
          <span className="text-xs font-bold text-foreground">NEXUS chat</span>
          <ConversationControls />
        </header>
        <ChatPanel wide />
      </section>
    </div>
  );
}
