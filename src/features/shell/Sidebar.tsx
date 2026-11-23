import { useQueryClient } from "@tanstack/react-query";
import { BarChart3, Moon, PanelLeftClose, PanelLeftOpen, Sun } from "lucide-react";

import { useNav, type View } from "@/lib/nav";
import { useTheme } from "@/lib/theme";
import type { SystemStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

import { VIEWS, warmView } from "./views";

export const NAV_GROUPS: Array<{ label: string; views: View[] }> = [
  { label: "Research", views: ["today", "ideas", "asset", "news", "markets"] },
  { label: "AI", views: ["chat", "briefs"] },
  { label: "Paper trading", views: ["portfolio", "record"] },
];

/** Workspace sidebar: grouped, labelled navigation; collapses to an icon rail. */
export function Sidebar({
  status,
  collapsed,
  onCollapse,
  onNavigate,
  className,
}: {
  status?: SystemStatus;
  collapsed: boolean;
  onCollapse?: () => void;
  onNavigate?: () => void;
  className?: string;
}) {
  const { view, go } = useNav();
  const client = useQueryClient();
  const { theme, toggle } = useTheme();

  const item = (key: View) => {
    const def = VIEWS[key];
    const Icon = def.icon;
    const active = view === key;
    return (
      <button
        key={key}
        onClick={() => {
          go(key);
          onNavigate?.();
        }}
        onMouseEnter={() => void warmView(client, key)}
        onFocus={() => void warmView(client, key)}
        aria-current={active ? "page" : undefined}
        title={collapsed ? def.label : undefined}
        className={cn(
          "group flex h-9 w-full items-center gap-3 rounded-[10px] px-2.5 text-[13px] font-medium transition-colors",
          collapsed && "justify-center px-0",
          active
            ? "bg-accent text-foreground"
            : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
        )}
      >
        <Icon className={cn("h-[18px] w-[18px] shrink-0", active && "text-primary")} />
        {!collapsed && <span className="truncate">{def.label}</span>}
      </button>
    );
  };

  return (
    <aside
      className={cn(
        "flex h-full flex-col border-r border-border bg-sidebar",
        collapsed ? "w-[64px] px-2" : "w-[232px] px-3",
        className,
      )}
    >
      <div className={cn("flex h-14 items-center gap-2.5", collapsed ? "justify-center" : "px-1")}>
        <div
          className="grid h-8 w-8 shrink-0 place-items-center rounded-[10px] bg-primary text-primary-foreground"
          title={status ? `AI: ${status.llm.provider} · ${status.llm.model}` : "NEXUS"}
        >
          <BarChart3 className="h-4 w-4" aria-hidden />
        </div>
        {!collapsed && (
          <div className="min-w-0 leading-tight">
            <div className="text-sm font-semibold">NEXUS</div>
            <div className="truncate text-[11px] text-muted-foreground">
              {status ? status.llm.model : "Evidence-based research"}
            </div>
          </div>
        )}
      </div>

      <nav aria-label="Main" className="mt-2 flex flex-1 flex-col gap-5 overflow-y-auto">
        {NAV_GROUPS.map((group) => (
          <div key={group.label} className="flex flex-col gap-0.5">
            {!collapsed && (
              <div className="px-2.5 pb-1 text-[11px] font-medium text-muted-foreground/80">
                {group.label}
              </div>
            )}
            {group.views.map(item)}
          </div>
        ))}
      </nav>

      <div className="flex flex-col gap-0.5 border-t border-border py-3">
        {item("settings")}
        <button
          onClick={toggle}
          title={collapsed ? (theme === "dark" ? "Light theme" : "Dark theme") : undefined}
          className={cn(
            "flex h-9 w-full items-center gap-3 rounded-[10px] px-2.5 text-[13px] font-medium text-muted-foreground transition-colors hover:bg-accent/60 hover:text-foreground",
            collapsed && "justify-center px-0",
          )}
        >
          {theme === "dark" ? (
            <Sun className="h-[18px] w-[18px]" />
          ) : (
            <Moon className="h-[18px] w-[18px]" />
          )}
          {!collapsed && <span>{theme === "dark" ? "Light theme" : "Dark theme"}</span>}
        </button>
        {onCollapse && (
          <button
            onClick={onCollapse}
            title={collapsed ? "Expand sidebar" : undefined}
            className={cn(
              "flex h-9 w-full items-center gap-3 rounded-[10px] px-2.5 text-[13px] font-medium text-muted-foreground transition-colors hover:bg-accent/60 hover:text-foreground",
              collapsed && "justify-center px-0",
            )}
          >
            {collapsed ? (
              <PanelLeftOpen className="h-[18px] w-[18px]" />
            ) : (
              <PanelLeftClose className="h-[18px] w-[18px]" />
            )}
            {!collapsed && <span>Collapse</span>}
          </button>
        )}
      </div>
    </aside>
  );
}
