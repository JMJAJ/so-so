import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";

import { api, streamChat } from "@/lib/api";
import { useNav } from "@/lib/nav";
import type { ChatMessage } from "@/lib/types";

interface ChatControl {
  /** Drawer visibility (the Chat page shows the same conversation full-width). */
  open: boolean;
  setOpen: (open: boolean) => void;
  conversationId: string | null;
  messages: ChatMessage[];
  busy: boolean;
  input: string;
  setInput: (text: string) => void;
  send: (text: string) => Promise<void>;
  stop: () => void;
  load: (id: string) => Promise<void>;
  reset: () => void;
  /** Open chat (drawer, or the page if it's showing) with a message; `send` submits it right away. */
  ask: (text?: string, send?: boolean) => void;
}

const ChatContext = createContext<ChatControl | null>(null);

export function ChatProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const { view } = useNav();
  const [open, setOpen] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const busyRef = useRef(false);
  const conversationRef = useRef<string | null>(null);
  conversationRef.current = conversationId;

  const load = useCallback(async (id: string) => {
    const data = await api.conversation(id);
    setConversationId(id);
    setMessages(data.messages);
  }, []);

  const reset = useCallback(() => {
    setConversationId(null);
    setMessages([]);
  }, []);

  const send = useCallback(
    async (text: string) => {
      const message = text.trim();
      if (!message || busyRef.current) return;
      busyRef.current = true;
      setBusy(true);
      setInput("");
      setMessages((current) => [
        ...current,
        { role: "user", text: message },
        { role: "assistant", text: "", tools: [], charts: [], pending: true },
      ]);
      const controller = new AbortController();
      abort.current = controller;
      const update = (fn: (last: ChatMessage) => ChatMessage) =>
        setMessages((current) => [...current.slice(0, -1), fn(current[current.length - 1])]);
      try {
        await streamChat(
          message,
          conversationRef.current,
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
            else if (event.type === "chart")
              update((last) => ({ ...last, charts: [...(last.charts ?? []), event.chart] }));
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
        busyRef.current = false;
        setBusy(false);
        abort.current = null;
        // A chat turn can create recommendations and open paper positions.
        void client.invalidateQueries();
      }
    },
    [client],
  );

  const stop = useCallback(() => abort.current?.abort(), []);

  const ask = useCallback(
    (text?: string, submit = false) => {
      if (view !== "chat") setOpen(true);
      if (!text) return;
      if (submit) void send(text);
      else setInput(text);
    },
    [send, view],
  );

  return (
    <ChatContext.Provider
      value={{
        open,
        setOpen,
        conversationId,
        messages,
        busy,
        input,
        setInput,
        send,
        stop,
        load,
        reset,
        ask,
      }}
    >
      {children}
    </ChatContext.Provider>
  );
}

export function useChat(): ChatControl {
  const value = useContext(ChatContext);
  if (!value) throw new Error("useChat must be used inside ChatProvider");
  return value;
}
