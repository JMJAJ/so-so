import { ChevronRight, Loader2, Send, Square, Wrench } from "lucide-react";
import { memo, useEffect, useRef, useState } from "react";

import { Markdown } from "@/features/shell/Markdown";
import { humanize } from "@/lib/format";
import type { ChatMessage } from "@/lib/types";
import { cn } from "@/lib/utils";

import { ChatChart } from "./ChatChart";
import { useChat } from "./chat-context";

export const COMMANDS: Array<[string, string]> = [
  ["/invest", "find the best trades now and open paper positions"],
  ["/chart GLD vs SPY", "show anything as a chart"],
  ["/scan", "rank today's best candidates"],
  ["/why NVDA", "full evidence review of one asset"],
  ["/recommend gold", "investigate and record one call"],
  ["/regime", "macro regime and what follows"],
  ["/news", "most important headlines + history"],
  ["/backtest", "which signals really work"],
  ["/record", "how the AI's calls performed"],
  ["/portfolio", "review open positions"],
];

/** One message. Memoized: while an answer streams, only the last message gets a new object,
 * so earlier messages (their markdown, charts and tool traces) don't re-render. */
const MessageItem = memo(function MessageItem({ message }: { message: ChatMessage }) {
  if (message.role === "user") {
    return (
      <div className="ml-8 rounded-xl border border-border bg-raised px-3 py-2 text-xs">
        {message.text}
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {(message.tools ?? []).length > 0 && <ToolTrace tools={message.tools ?? []} />}
      {(message.charts ?? []).map((chart, i) => (
        <ChatChart key={i} chart={chart} />
      ))}
      {message.text ? <Markdown text={message.text} /> : null}
      {message.pending && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin text-bull" /> researching
        </div>
      )}
    </div>
  );
});

/** Messages + composer, shared by the drawer and the full Chat page. */
export function ChatPanel({ wide = false }: { wide?: boolean }) {
  const { messages, busy, input, setInput, send, stop } = useChat();
  const scroller = useRef<HTMLDivElement>(null);
  // Follow new output only while the reader is at the bottom; scrolling up to read stops it.
  const following = useRef(true);

  useEffect(() => {
    const el = scroller.current;
    if (!el || !following.current) return;
    const frame = window.requestAnimationFrame(() => el.scrollTo({ top: el.scrollHeight }));
    return () => window.cancelAnimationFrame(frame);
  }, [messages]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div
        ref={scroller}
        className="min-h-0 flex-1 overflow-y-auto px-3 py-4"
        onScroll={(event) => {
          const el = event.currentTarget;
          following.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
        }}
      >
        <div className={cn("space-y-4", wide && "mx-auto max-w-3xl")}>
          {messages.length === 0 && <Welcome wide={wide} onPick={(command) => setInput(command)} />}
          {messages.map((message, index) => (
            <MessageItem key={index} message={message} />
          ))}
        </div>
      </div>

      <form
        className="border-t border-border p-3"
        onSubmit={(event) => {
          event.preventDefault();
          void send(input);
        }}
      >
        <div className={cn("flex gap-2", wide && "mx-auto max-w-3xl")}>
          <textarea
            className="terminal-input min-h-[44px] resize-none"
            rows={wide ? 3 : 2}
            placeholder="Ask, or type / for commands (try /invest)…"
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
            <button type="button" className="icon-button" onClick={stop} aria-label="Stop">
              <Square className="h-4 w-4" />
            </button>
          ) : (
            <button
              className="icon-button !border-[#1f3a27] !text-bull"
              aria-label="Send"
              disabled={!input.trim()}
            >
              <Send className="h-4 w-4" />
            </button>
          )}
        </div>
        {input.startsWith("/") && !input.includes(" ") && (
          <div className={cn("mt-2 flex flex-wrap gap-1", wide && "mx-auto max-w-3xl")}>
            {COMMANDS.filter(([command]) => command.startsWith(input.split(" ")[0])).map(
              ([command, help]) => (
                <button
                  type="button"
                  key={command}
                  title={help}
                  className="rounded-lg border border-border px-1.5 py-0.5 text-xs hover:border-[#2f352f]"
                  onClick={() => setInput(command.split(" ")[0] + " ")}
                >
                  {command.split(" ")[0]}
                </button>
              ),
            )}
          </div>
        )}
      </form>
    </div>
  );
}

function Welcome({ wide, onPick }: { wide: boolean; onPick: (command: string) => void }) {
  return (
    <div className="space-y-3">
      <p className="text-xs leading-relaxed text-muted-foreground">
        Ask anything about markets. The AI answers with the same tools the analyst uses: event
        studies, historical analogs, correlations, classified news, the quant model and your track
        record. It can draw charts and open paper trades.
      </p>
      <div className={cn("grid gap-1.5", wide && "sm:grid-cols-2")}>
        {COMMANDS.map(([command, help]) => (
          <button
            key={command}
            className="rounded-lg flex items-center justify-between gap-3 border border-border px-2.5 py-1.5 text-left text-[11px] hover:border-[#2f352f]"
            onClick={() => onPick(command.includes(" ") ? command : command + " ")}
          >
            <span className="shrink-0 font-bold text-foreground">{command}</span>
            <span className="truncate text-muted-foreground">{help}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function ToolTrace({ tools }: { tools: NonNullable<ChatMessage["tools"]> }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border border-border bg-background/50 text-xs">
      <button
        className="flex w-full items-center gap-1.5 px-2 py-1 text-left text-muted-foreground"
        onClick={() => setOpen((v) => !v)}
      >
        <ChevronRight
          className={cn("h-3 w-3 shrink-0 transition-transform", open && "rotate-90")}
        />
        <Wrench className="h-3 w-3 shrink-0" />
        {tools.length} tool call{tools.length > 1 ? "s" : ""}:{" "}
        {Array.from(new Set(tools.map((t) => humanize(t.name)))).join(", ")}
      </button>
      {open && (
        <ul className="space-y-1 border-t border-border px-2 py-1.5">
          {tools.map((tool, i) => (
            <li key={i} className={cn("break-all", tool.is_error && "text-bear")}>
              <span className="font-bold text-foreground">{tool.name}</span>{" "}
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
