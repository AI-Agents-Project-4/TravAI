import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import type { Option, Plan } from "@/lib/types";
import { PlanEditor } from "./PlanEditor";

const { api } = vi.hoisted(() => ({ api: { redraftPlan: vi.fn(), savePlan: vi.fn() } }));
vi.mock("@/lib/api", () => ({ api }));

const usd = (amount: number) => ({ amount, currency: "USD" });
const option = (id: string, title: string, kind: Option["kind"], amount: number, estimate = false): Option => ({
  id,
  kind,
  title,
  price: usd(amount),
  price_is_estimate: estimate,
  source_url: `https://example.com/${id}`,
  fetched_at: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
});

const options = [
  option("f", "Round trip DEN – Tokyo", "flight", 1450),
  option("h", "Central hotel", "hotel", 740),
  option("senso", "Senso-ji Temple", "activity", 0),
  option("tea", "Tea ceremony", "activity", 45),
  option("fuji", "Mount Fuji day trip", "activity", 140, true),
];

const plan: Plan = {
  id: "p1",
  trip_id: "t1",
  title: "Temples and history",
  summary: "Landmarks, slower pace.",
  flight_option_id: "f",
  hotel_option_id: "h",
  days: [
    { day: 1, items: [{ option_id: "tea", locked: false }] },
    { day: 2, items: [] },
    { day: 3, items: [{ option_id: "senso", locked: false }] },
  ],
  cost_breakdown: [],
  total: usd(2610), // 1450 + 740 + 45 + 375 meals/transport
  budget: usd(5000),
  warnings: [],
  saved: false,
};

const total = () => within(screen.getByRole("status")).getByText(/\$/, { selector: "p.text-3xl" }).textContent;

beforeEach(() => {
  api.redraftPlan.mockReset();
  api.savePlan.mockReset();
});

describe("PlanEditor", () => {
  test("every price shows its source and age, and estimates are labeled", () => {
    render(<PlanEditor initialPlan={plan} options={options} />);
    const links = screen.getAllByRole("link", { name: /source for/i });
    expect(links.length).toBeGreaterThanOrEqual(4);
    for (const a of links) {
      expect(a.getAttribute("href")).toMatch(/^https:\/\/example\.com\//);
      expect(a.getAttribute("rel")).toContain("noopener");
    }
    expect(screen.getAllByText(/fetched 2 hours ago/).length).toBe(links.length);
    expect(screen.getByText("estimate")).toBeDefined(); // Fuji, in "other options"
  });

  test("the running total follows removes and adds", () => {
    render(<PlanEditor initialPlan={plan} options={options} />);
    expect(total()).toBe("$2,610");
    fireEvent.click(screen.getByRole("button", { name: "Remove Tea ceremony" }));
    expect(total()).toBe("$2,565");
    fireEvent.click(screen.getByRole("button", { name: "Add Mount Fuji day trip" }));
    expect(total()).toBe("$2,705");
    expect(screen.getByText(/left of your \$5,000 budget/)).toBeDefined();
  });

  test("shows when the edits go over budget", () => {
    render(<PlanEditor initialPlan={{ ...plan, budget: usd(2650) }} options={options} />);
    fireEvent.click(screen.getByRole("button", { name: "Add Mount Fuji day trip" }));
    expect(screen.getByText(/\$100 over your \$2,650 budget/)).toBeDefined();
  });

  test("moving an item to another day keeps it in a redraft", () => {
    render(<PlanEditor initialPlan={plan} options={options} />);
    fireEvent.change(screen.getByLabelText("Move Senso-ji Temple to"), { target: { value: "1" } });
    const day1 = screen.getByRole("region", { name: "Day 1" });
    expect(within(day1).getByText("Senso-ji Temple")).toBeDefined();
    expect(within(day1).getByRole("button", { name: "Keep Senso-ji Temple in a redraft" }).getAttribute("aria-pressed")).toBe("true");
  });

  test("redraft sends locked items and removed ids, then lists what was dropped", async () => {
    api.redraftPlan.mockImplementation(async (_id: string, body: { days: Plan["days"] }) => ({
      plan: { ...plan, days: body.days.map((d) => ({ ...d, items: d.items.filter((i) => i.option_id !== "senso") })) },
      dropped_items: [{ option_id: "senso", reason: "Dropped to stay under your budget (saves $0)." }],
    }));
    render(<PlanEditor initialPlan={plan} options={options} />);
    fireEvent.click(screen.getByRole("button", { name: "Remove Tea ceremony" }));
    fireEvent.click(screen.getByRole("button", { name: "Add Mount Fuji day trip" }));
    fireEvent.click(screen.getByRole("button", { name: "Redraft around my changes" }));

    await waitFor(() => expect(api.redraftPlan).toHaveBeenCalled());
    const [id, body] = api.redraftPlan.mock.calls[0];
    expect(id).toBe("p1");
    expect(body.removed_option_ids).toEqual(["tea"]);
    expect(body.days[0].items).toEqual([{ option_id: "fuji", locked: true }]);

    expect(await screen.findByText(/the planner dropped/i)).toBeDefined();
    expect(screen.getByText(/saves \$0/)).toBeDefined();
  });

  test("a failed redraft keeps the user's edits", async () => {
    api.redraftPlan.mockRejectedValue(new Error("Planner timed out."));
    render(<PlanEditor initialPlan={plan} options={options} />);
    fireEvent.click(screen.getByRole("button", { name: "Remove Tea ceremony" }));
    fireEvent.click(screen.getByRole("button", { name: "Redraft around my changes" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/timed out/);
    expect(within(screen.getByRole("region", { name: "Day 1" })).queryByText("Tea ceremony")).toBeNull();
    expect(total()).toBe("$2,565");
  });

  test("save sends the running total the user saw", async () => {
    api.savePlan.mockImplementation(async (p: Plan) => ({ ...p, saved: true }));
    render(<PlanEditor initialPlan={plan} options={options} />);
    fireEvent.click(screen.getByRole("button", { name: "Add Mount Fuji day trip" }));
    fireEvent.click(screen.getByRole("button", { name: "Save plan" }));
    await waitFor(() => expect(api.savePlan).toHaveBeenCalled());
    expect(api.savePlan.mock.calls[0][0].total).toEqual(usd(2750));
    expect(await screen.findByText(/plan saved/i)).toBeDefined();
  });
});
