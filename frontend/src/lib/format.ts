import type { Money } from "./types";

/**
 * Formats money with its currency, in whole units. Costs round UP (product
 * rule 1: never underestimate), so $1,249.01 shows as $1,250. Pass
 * `round: "down"` for what's *left* of a budget, so that isn't overstated.
 */
export function formatMoney(
  money: Money,
  { round = "up", locale = "en-US" }: { round?: "up" | "down"; locale?: string } = {},
): string {
  // Round to cents first so float noise (1249.0000001) doesn't add a unit.
  const cents = Math.round(money.amount * 100);
  const whole = round === "up" ? Math.ceil(cents / 100) : Math.floor(cents / 100);
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency: money.currency,
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(whole);
}

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 365 * 24 * 60 * 60],
  ["month", 30 * 24 * 60 * 60],
  ["week", 7 * 24 * 60 * 60],
  ["day", 24 * 60 * 60],
  ["hour", 60 * 60],
  ["minute", 60],
];

/** "3 hours ago" for a fetched_at timestamp. */
export function formatAge(iso: string, now: Date = new Date(), locale = "en-US"): string {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "at an unknown time";
  const seconds = Math.round((now.getTime() - then.getTime()) / 1000);
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size) return rtf.format(-Math.trunc(seconds / size), unit);
  }
  return "just now";
}

/** Exact timestamp for tooltips, e.g. "Nov 21, 2026, 3:04 PM". */
export function formatTimestamp(iso: string, locale = "en-US"): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(d);
}

/**
 * Returns the URL only if it's http(s). source_url comes from scraped web
 * pages, which are untrusted (threat model), so a `javascript:` or `data:`
 * URL must never become a clickable link.
 */
export function safeHttpUrl(url: string): string | null {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null;
  } catch {
    return null;
  }
}

/** Hostname of a source URL for compact link text ("booking.com"). */
export function sourceLabel(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "source";
  }
}

const CATEGORY_LABELS: Record<string, string> = {
  flight: "Flight",
  hotel: "Hotel",
  activity: "Activities",
  food: "Food",
  transport: "Transport",
  other: "Meals, local transport, fees",
};

export function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category] ?? category;
}
