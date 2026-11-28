import { describe, expect, test } from "vitest";
import { formatAge, formatMoney, safeHttpUrl, sourceLabel } from "./format";

describe("formatMoney", () => {
  test("shows the currency", () => {
    expect(formatMoney({ amount: 5000, currency: "USD" })).toBe("$5,000");
    expect(formatMoney({ amount: 5000, currency: "EUR" })).toBe("€5,000");
  });

  test("never rounds down", () => {
    expect(formatMoney({ amount: 1249.01, currency: "USD" })).toBe("$1,250");
    expect(formatMoney({ amount: 1249.5, currency: "USD" })).toBe("$1,250");
  });

  test("rounds down when asked, for what's left of a budget", () => {
    expect(formatMoney({ amount: 0.5, currency: "USD" }, { round: "down" })).toBe("$0");
    expect(formatMoney({ amount: 10.99, currency: "USD" }, { round: "down" })).toBe("$10");
  });

  test("ignores float noise below a cent", () => {
    expect(formatMoney({ amount: 0.1 + 0.2 + 1249.7, currency: "USD" })).toBe("$1,250");
    expect(formatMoney({ amount: 1249.0000001, currency: "USD" })).toBe("$1,249");
  });
});

describe("formatAge", () => {
  const now = new Date("2026-11-21T12:00:00Z");
  test("relative time", () => {
    expect(formatAge("2026-11-21T09:00:00Z", now)).toBe("3 hours ago");
    expect(formatAge("2026-11-20T12:00:00Z", now)).toBe("yesterday");
    expect(formatAge("2026-11-21T11:59:30Z", now)).toBe("just now");
  });
  test("bad timestamps don't crash", () => {
    expect(formatAge("not a date", now)).toBe("at an unknown time");
  });
});

describe("safeHttpUrl", () => {
  test("allows http and https", () => {
    expect(safeHttpUrl("https://www.example.com/a")).toBe("https://www.example.com/a");
    expect(safeHttpUrl("http://example.com")).toBe("http://example.com/");
  });
  test("rejects anything a scraped page could use to run script", () => {
    expect(safeHttpUrl("javascript:alert(1)")).toBeNull();
    expect(safeHttpUrl(" JavaScript:alert(1)")).toBeNull();
    expect(safeHttpUrl("data:text/html,<script>alert(1)</script>")).toBeNull();
    expect(safeHttpUrl("/relative")).toBeNull();
  });
  test("labels by hostname", () => {
    expect(sourceLabel("https://www.booking.com/hotel/x")).toBe("booking.com");
  });
});
