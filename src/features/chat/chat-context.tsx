import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

interface ChatControl {
  open: boolean;
  draft: { text: string; send: boolean; nonce: number } | null;
  setOpen: (open: boolean) => void;
  /** Open the chat drawer, optionally with a message (sent immediately when `send`). */
  ask: (text?: string, send?: boolean) => void;
}

const ChatContext = createContext<ChatControl | null>(null);

export function ChatProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<ChatControl["draft"]>(null);
  const ask = useCallback((text?: string, send = false) => {
    setOpen(true);
    if (text) setDraft({ text, send, nonce: Date.now() });
  }, []);
  return (
    <ChatContext.Provider value={{ open, draft, setOpen, ask }}>{children}</ChatContext.Provider>
  );
}

export function useChat(): ChatControl {
  const value = useContext(ChatContext);
  if (!value) throw new Error("useChat must be used inside ChatProvider");
  return value;
}
