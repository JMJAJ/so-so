export function pct(value: number | null | undefined, digits = 1, signed = true): string {
  if (value == null || Number.isNaN(value)) return "—";
  const v = value * 100;
  return `${signed && v > 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

export function num(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function price(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  const digits = abs >= 1000 ? 2 : abs >= 10 ? 2 : abs >= 1 ? 4 : 5;
  return value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function money(value: number | null | undefined, signed = false, digits = 0): string {
  if (value == null || Number.isNaN(value)) return "—";
  const text = Math.abs(value).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  if (!signed) return value < 0 ? `-${text}` : text;
  return `${value > 0 ? "+" : value < 0 ? "-" : ""}${text}`;
}

export function signed(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}`;
}

export function ago(value: string | null | undefined): string {
  if (!value) return "never";
  const then = new Date(value.length === 10 ? `${value}T00:00:00Z` : value).getTime();
  const seconds = Math.round((Date.now() - then) / 1000);
  if (Number.isNaN(seconds)) return value;
  if (seconds < 0) {
    const ahead = -seconds;
    if (ahead < 3600) return `in ${Math.round(ahead / 60)}m`;
    if (ahead < 86400) return `in ${Math.round(ahead / 3600)}h`;
    return `in ${Math.round(ahead / 86400)}d`;
  }
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

export function shortDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value.length === 10 ? `${value}T00:00:00Z` : value);
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "2-digit" });
}

export function tone(value: number | null | undefined): string {
  if (value == null || value === 0 || Number.isNaN(value)) return "text-muted-foreground";
  return value > 0 ? "text-bull" : "text-bear";
}

export function humanize(value: string): string {
  return value.replace(/_/g, " ");
}
