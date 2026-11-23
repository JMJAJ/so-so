import { useCallback, useEffect, useState } from "react";

export type Theme = "dark" | "light";
const STORAGE_KEY = "nexus.theme";

/** Runs in <head> before first paint so a light-theme user never sees a dark flash. */
export const THEME_BOOT_SCRIPT = `try{if(localStorage.getItem("${STORAGE_KEY}")==="light"){var d=document.documentElement;d.classList.remove("dark");d.classList.add("light")}}catch(e){}`;

function readTheme(): Theme {
  if (typeof document === "undefined") return "dark";
  return document.documentElement.classList.contains("light") ? "light" : "dark";
}

function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  root.classList.toggle("light", theme === "light");
  root.classList.toggle("dark", theme === "dark");
  try {
    window.localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // Storage blocked: the theme applies for this visit only.
  }
  window.dispatchEvent(new CustomEvent("nexus-theme", { detail: theme }));
}

/** Current theme and a toggle. Every caller re-renders when any of them switches. */
export function useTheme(): { theme: Theme; toggle: () => void } {
  const [theme, setTheme] = useState<Theme>(readTheme);
  useEffect(() => {
    const onChange = () => setTheme(readTheme());
    window.addEventListener("nexus-theme", onChange);
    return () => window.removeEventListener("nexus-theme", onChange);
  }, []);
  const toggle = useCallback(() => applyTheme(readTheme() === "dark" ? "light" : "dark"), []);
  return { theme, toggle };
}

/** A CSS custom property's resolved value, for canvas libraries that can't read var(). */
export function cssVar(name: string, fallback = "#888"): string {
  if (typeof document === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}
