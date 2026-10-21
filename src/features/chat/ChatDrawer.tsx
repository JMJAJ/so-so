import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Maximize2, Plus, Trash2, X } from "lucide-react";

import { api } from "@/lib/api";
import { useNav } from "@/lib/nav";

import { ChatPanel } from "./ChatPanel";
import { useChat } from "./chat-context";

/** Conversation picker + new/delete, shared by the drawer header and the Chat page. */
export function ConversationControls() {
  const client = useQueryClient();
  const { conversationId, load, reset, busy } = useChat();
  const conversations = useQuery({ queryKey: ["conversations"], queryFn: api.conversations });
  return (
    <>
      <select
        className="terminal-select !min-h-0 min-w-0 flex-1 !py-1 text-[11px]"
        value={conversationId ?? ""}
        disabled={busy}
        onChange={(event) => (event.target.value ? void load(event.target.value) : reset())}
      >
        <option value="">New conversation</option>
        {(conversations.data ?? []).map((conv) => (
          <option key={conv.id} value={conv.id}>
            {conv.title}
          </option>
        ))}
      </select>
      <button
        className="icon-button !p-1.5"
        title="New conversation"
        onClick={reset}
        disabled={busy}
      >
        <Plus className="h-3.5 w-3.5" />
      </button>
      {conversationId && (
        <button
          className="icon-button !p-1.5"
          title="Delete conversation"
          disabled={busy}
          onClick={async () => {
            if (!window.confirm("Delete this conversation?")) return;
            await api.deleteConversation(conversationId);
            reset();
            void client.invalidateQueries({ queryKey: ["conversations"] });
          }}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      )}
    </>
  );
}

export default function ChatDrawer() {
  const { open, setOpen } = useChat();
  const { view, go } = useNav();
  if (!open || view === "chat") return null;

  return (
    <aside className="fixed inset-y-0 right-0 z-40 flex w-full flex-col border-l border-border bg-card shadow-2xl sm:w-[460px]">
      <header className="flex items-center gap-2 border-b border-border px-3 py-2.5">
        <span className="text-[10px] font-bold uppercase tracking-[0.2em] text-primary">
          NEXUS chat
        </span>
        <ConversationControls />
        <button
          className="icon-button !p-1.5"
          title="Open full page"
          onClick={() => {
            setOpen(false);
            go("chat");
          }}
        >
          <Maximize2 className="h-3.5 w-3.5" />
        </button>
        <button
          className="icon-button !p-1.5"
          onClick={() => setOpen(false)}
          aria-label="Close chat"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </header>
      <ChatPanel />
    </aside>
  );
}
