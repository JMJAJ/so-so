import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  Outlet,
  Link,
  createRootRouteWithContext,
  useRouter,
  HeadContent,
  Scripts,
} from "@tanstack/react-router";
import type { ReactNode } from "react";

import appCss from "../styles.css?url";
import { Toaster } from "@/components/ui/sonner";

function NotFoundComponent() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="terminal-panel max-w-md p-8 text-center">
        <div className="font-mono text-xs uppercase tracking-widest text-primary">
          ERR_404 // ROUTE_NOT_FOUND
        </div>
        <h1 className="mt-4 font-display text-6xl font-bold text-foreground">404</h1>
        <p className="mt-3 text-sm text-muted-foreground">This terminal path does not exist.</p>
        <Link
          to="/"
          className="mt-6 inline-flex items-center justify-center rounded-sm bg-primary px-4 py-2 text-xs font-bold uppercase tracking-widest text-primary-foreground"
        >
          Return to terminal
        </Link>
      </div>
    </div>
  );
}

function ErrorComponent({ error, reset }: { error: Error; reset: () => void }) {
  console.error(error);
  const router = useRouter();

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="terminal-panel max-w-md p-8 text-center">
        <div className="font-mono text-xs uppercase tracking-widest text-destructive">
          SYS_ERROR // RUNTIME
        </div>
        <h1 className="mt-4 font-display text-2xl font-bold">Terminal disconnected</h1>
        <p className="mt-2 text-sm text-muted-foreground">An exception interrupted the feed.</p>
        <div className="mt-6 flex justify-center gap-2">
          <button
            onClick={() => {
              router.invalidate();
              reset();
            }}
            className="rounded-sm bg-primary px-4 py-2 text-xs font-bold uppercase tracking-widest text-primary-foreground"
          >
            Reconnect
          </button>
          <a
            href="/"
            className="rounded-sm border border-border px-4 py-2 text-xs font-bold uppercase tracking-widest"
          >
            Home
          </a>
        </div>
      </div>
    </div>
  );
}

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  head: () => ({
    meta: [
      { charSet: "utf-8" },
      { name: "viewport", content: "width=device-width, initial-scale=1" },
      { title: "NEXUS // Evidence-based investment research" },
      {
        name: "description",
        content:
          "AI investment research grounded in market and news history, verified with paper trading.",
      },
      { name: "theme-color", content: "#0a0a0a" },
      { property: "og:title", content: "NEXUS // Evidence-based investment research" },
      {
        property: "og:description",
        content:
          "AI investment research grounded in market and news history, verified with paper trading.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
    links: [{ rel: "stylesheet", href: appCss }],
  }),
  shellComponent: RootShell,
  component: RootComponent,
  notFoundComponent: NotFoundComponent,
  errorComponent: ErrorComponent,
});

function RootShell({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className="dark">
      <head>
        <HeadContent />
      </head>
      <body>
        {children}
        <Scripts />
      </body>
    </html>
  );
}

function RootComponent() {
  const { queryClient } = Route.useRouteContext();

  return (
    <QueryClientProvider client={queryClient}>
      <Outlet />
      <Toaster theme="dark" />
    </QueryClientProvider>
  );
}
