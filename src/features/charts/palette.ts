import { cssVar } from "@/lib/theme";

/** Canvas chart colours, read from the theme tokens in styles.css (canvas can't use var()). */
export function chartPalette() {
  return {
    bg: cssVar("--panel", "#111113"),
    text: cssVar("--muted-foreground", "#8d8d97"),
    grid: cssVar("--grid", "#18181c"),
    border: cssVar("--border", "#222227"),
    up: cssVar("--bull", "#2ec27e"),
    down: cssVar("--bear", "#f2555f"),
    upSoft: cssVar("--bull-line", "#1d3d2e"),
    downSoft: cssVar("--bear-line", "#44222a"),
    volume: cssVar("--strong", "#33333a"),
    amber: cssVar("--foreground", "#ececef"),
    primary: cssVar("--primary", "#3b7bff"),
    muted: cssVar("--muted-foreground", "#8d8d97"),
  };
}
