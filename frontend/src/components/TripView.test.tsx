import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import type { Option, Plan } from "@/lib/types";
import { Price } from "./Price";
import { Infeasible, PlanComparison } from "./TripView";

const usd = (amount: number) => ({ amount, currency: "USD" });
const flight: Option = {
  id: "f",
  kind: "flight",
  title: "Round trip DEN – Tokyo",
  price: usd(1450),
  price_is_estimate: false,
  source_url: "https://example.com/f",
  fetched_at: "2026-11-21T00:00:00Z",
};
const plan = (id: string, title: string, total: number): Plan => ({
  id,
  trip_id: "t1",
  title,
  summary: "",
  flight_option_id: "f",
  days: [{ day: 1, items: [] }],
  cost_breakdown: [{ category: "flight", total: usd(1450) }],
  total: usd(total),
  budget: usd(5000),
  warnings: [{ kind: "safety", message: "Advisory in effect." }],
  saved: false,
});

describe("PlanComparison", () => {
  test("shows three plans against the budget, links to each, and a shared warning once", () => {
    render(
      <PlanComparison
        plans={[plan("a", "Temples and history", 4200), plan("b", "Food and nightlife", 4999.5), plan("c", "Day trips", 5100)]}
        options={[flight]}
      />,
    );
    expect(screen.getAllByRole("article")).toHaveLength(3);
    expect(screen.getByText("$800 under your $5,000 budget")).toBeDefined();
    expect(screen.getByText("$0 under your $5,000 budget")).toBeDefined(); // $0.50 left rounds down
    expect(screen.getByText("$100 over your $5,000 budget")).toBeDefined();
    expect(screen.getByRole("link", { name: /view and edit temples and history/i }).getAttribute("href")).toBe("/plans/a");
    expect(screen.getAllByText("Advisory in effect.")).toHaveLength(1);
  });
});

describe("Infeasible", () => {
  test("says so honestly with the minimum cost", () => {
    render(<Infeasible reason="Flights alone cost more." minCost={usd(9800)} budget={usd(500)} />);
    expect(screen.getByRole("heading", { name: /doesn't fit the budget/i })).toBeDefined();
    expect(screen.getByText("$9,800")).toBeDefined();
    expect(screen.getByRole("link", { name: "Change the trip" }).getAttribute("href")).toBe("/");
  });
});

describe("Price", () => {
  test("a javascript: source URL from a scraped page is not rendered as a link", () => {
    render(<Price option={{ ...flight, source_url: "javascript:alert(1)" }} />);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText("source link unavailable")).toBeDefined();
  });
});
