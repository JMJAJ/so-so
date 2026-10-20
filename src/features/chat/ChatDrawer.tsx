import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Loader2, Plus, Send, Square, Trash2, Wrench, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Markdown } from "@/features/shell/Markdown";
import { api, streamChat } from "@/lib/api";
import { humanize } from "@/lib/format";
import type { ChatMessage } from "@/lib/types";
import { cn } from "@/lib/utils";

import { useChat } from "./chat-context";

const COMMANDS = [
  ["/scan", "rank today's best candidates"],
  ["/why NVDA", "full evidence review of one asset"],
  ["/recommend gold", "investigate and record a call"],
  ["/regime", "macro regime and what follows"],
  ["/news", "most important headlines + history"],
  ["/backtest", "which signals really work"],
  ["/record", "how the AI's calls performed"],
  ["/portfolio", "review open positions"],
];

export default function ChatDrawer() {
  const { open, setOpen, draft } = useChat();
  const client = useQueryClient();
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const conversations = useQuery({
    queryKey: ["conversations"],
    queryFn: api.conversations,
    enabled: open,
  });

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight });
  }, [messages]);

  const load = useCallback(async (id: string) => {
    const data = await api.conversation(id);
    setConversationId(id);
    setMessages(data.messages.map((m) => ({ role: m.role, text: m.text, tools: m.tools })));
  }, []);

  const send = useCallback(
    async (text: string) => {
      const message = text.trim();
      if (!message || busy) return;
      setInput("");
      setBusy(true);
      setMessages((current) => [
        ...current,
        { role: "user", text: message },
        { role: "assistant", text: "", tools: [], pending: true },
      ]);
      const controller = new AbortController();
      abort.current = controller;
      const update = (fn: (last: ChatMessage) => ChatMessage) =>
        setMessages((current) => [...current.slice(0, -1), fn(current[current.length - 1])]);
      try {
        await streamChat(
          message,
          conversationId,
          (event) => {
            if (event.type === "conversation") setConversationId(event.id);
            else if (event.type === "text")
              update((last) => ({ ...last, text: last.text + event.text }));
            else if (event.type === "tool_call")
              update((last) => ({
                ...last,
                text: last.text ? `${last.text}\n\n` : "",
                tools: [
                  ...(last.tools ?? []),
                  { id: event.id, name: event.name, input: event.input },
                ],
              }));
            else if (event.type === "tool_result")
              update((last) => ({
                ...last,
                tools: (last.tools ?? []).map((tool) =>
                  tool.id === event.id
                    ? { ...tool, is_error: event.is_error, preview: event.preview }
                    : tool,
                ),
              }));
            else if (event.type === "error")
              update((last) => ({ ...last, text: `${last.text}\n\n**Error:** ${event.message}` }));
          },
          controller.signal,
        );
      } catch (error) {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          update((last) => ({
            ...last,
            text: `${last.text}\n\n**Error:** ${error instanceof Error ? error.message : "request failed"}`,
          }));
        }
      } finally {
        update((last) => ({ ...last, pending: false }));
        setBusy(false);
        abort.current = null;
        void client.invalidateQueries({ queryKey: ["conversations"] });
        void client.invalidateQueries({ queryKey: ["dashboard"] });
      }
    },
    [busy, conversationId, client],
  );

  useEffect(() => {
    if (!draft) return;
    if (draft.send) void send(draft.text);
    else setInput(draft.text);
    // Only react to a new draft, not to `send` identity changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft?.nonce]);

  if (!open) return null;

  return (
    <aside className="fixed inset-y-0 right-0 z-40 flex w-full flex-col border-l border-border bg-card shadow-2xl sm:w-[460px]">
      <header className="flex items-center gap-2 border-b border-border px-3 py-2.5">
        <span className="text-[10px] font-bold uppercase tracking-[0.2em] text-primary">
          NEXUS chat
        </span>
        <select
          className="terminal-select !min-h-0 min-w-0 flex-1 !py-1 text-[11px]"
          value={conversationId ?? ""}
          onChange={(event) =>
            event.target.value
              ? void load(event.target.value)
              : (setConversationId(null), setMessages([]))
          }
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
          onClick={() => {
            setConversationId(null);
            setMessages([]);
          }}
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
        {conversationId && (
          <button
            className="icon-button !p-1.5"
            title="Delete conversation"
            onClick={async () => {
              await api.deleteConversation(conversationId);
              setConversationId(null);
              setMessages([]);
              void client.invalidateQueries({ queryKey: ["conversations"] });
            }}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        )}
        <button
          className="icon-button !p-1.5"
          onClick={() => setOpen(false)}
          aria-label="Close chat"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </header>

      <div ref={scroller} className="flex-1 space-y-4 overflow-y-auto px-3 py-4">
        {messages.length === 0 && (
          <div className="space-y-3">
            <p className="text-xs leading-relaxed text-muted-foreground">
              Ask anything about markets. The AI answers with the same tools the analyst uses: event
              studies, historical analogs, correlations, classified news, the quant model and your
              track record.
            </p>
            <div className="grid gap-1.5">
              {COMMANDS.map(([command, help]) => (
                <button
                  key={command}
                  className="flex items-center justify-between border border-border px-2.5 py-1.5 text-left text-[11px] hover:border-primary"
                  onClick={() => setInput(command + " ")}
                >
                  <span className="font-bold text-primary">{command}</span>
                  <span className="text-muted-foreground">{help}</span>
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((message, index) =>
          message.role === "user" ? (
            <div
              key={index}
              className="ml-8 border border-primary/30 bg-primary/5 px-3 py-2 text-xs"
            >
              {message.text}
            </div>
          ) : (
            <div key={index} className="space-y-2">
              {(message.tools ?? []).length > 0 && <ToolTrace tools={message.tools ?? []} />}
              {message.text ? <Markdown text={message.text} /> : null}
              {message.pending && (
                <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
                  <Loader2 className="h-3 w-3 animate-spin text-primary" /> researching
                </div>
              )}
            </div>
          ),
        )}
      </div>

      <form
        className="border-t border-border p-3"
        onSubmit={(event) => {
          event.preventDefault();
          void send(input);
        }}
      >
        <div className="flex gap-2">
          <textarea
            className="terminal-input min-h-[44px] resize-none"
            rows={2}
            placeholder="Ask, or type / for commands…"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void send(input);
              }
            }}
          />
          {busy ? (
            <button
              type="button"
              className="icon-button"
              onClick={() => abort.current?.abort()}
              aria-label="Stop"
            >
              <Square className="h-4 w-4" />
            </button>
          ) : (
            <button
              className="icon-button !border-primary/60 !text-primary"
              aria-label="Send"
              disabled={!input.trim()}
            >
              <Send className="h-4 w-4" />
            </button>
          )}
        </div>
        {input.startsWith("/") && !input.includes(" ") && (
          <div className="mt-2 flex flex-wrap gap-1">
            {COMMANDS.filter(([command]) => command.startsWith(input.split(" ")[0])).map(
              ([command]) => (
                <button
                  type="button"
                  key={command}
                  className="border border-border px-1.5 py-0.5 text-[10px] hover:border-primary"
                  onClick={() => setInput(command.split(" ")[0] + " ")}
                >
                  {command.split(" ")[0]}
                </button>
              ),
            )}
          </div>
        )}
      </form>
    </aside>
  );
}

function ToolTrace({ tools }: { tools: NonNullable<ChatMessage["tools"]> }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border border-border bg-background/50 text-[10px]">
      <button
        className="flex w-full items-center gap-1.5 px-2 py-1 text-muted-foreground"
        onClick={() => setOpen((v) => !v)}
      >
        <ChevronRight className={cn("h-3 w-3 transition-transform", open && "rotate-90")} />
        <Wrench className="h-3 w-3" />
        {tools.length} tool call{tools.length > 1 ? "s" : ""}:{" "}
        {Array.from(new Set(tools.map((t) => humanize(t.name)))).join(", ")}
      </button>
      {open && (
        <ul className="space-y-1 border-t border-border px-2 py-1.5">
          {tools.map((tool, i) => (
            <li key={i} className={cn("break-all", tool.is_error && "text-bear")}>
              <span className="font-bold text-primary">{tool.name}</span>{" "}
              {JSON.stringify(tool.input)}
              {tool.preview && (
                <div className="mt-0.5 line-clamp-2 text-muted-foreground">{tool.preview}</div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
