import { createFileRoute } from "@tanstack/react-router";

import TerminalApp from "@/features/terminal/TerminalApp";

export const Route = createFileRoute("/")({
  ssr: false,
  head: () => ({
    meta: [
      { title: "NEXUS // Trustworthy Paper Trading" },
      {
        name: "description",
        content: "A local, guarded AI paper-trading terminal with deterministic risk controls.",
      },
    ],
  }),
  component: TerminalApp,
});
