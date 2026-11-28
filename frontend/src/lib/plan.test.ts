import { describe, expect, test } from "vitest";
import {
  addableOptions,
  addItem,
  indexOptions,
  isOverBudget,
  moveItem,
  removeItem,
  runningTotal,
  toggleLock,
} from "./plan";
import type { Option, Plan } from "./types";

const usd = (amount: number) => ({ amount, currency: "USD" });

function option(id: string, kind: Option["kind"], amount: number, currency = "USD"): Option {
  return {
    id,
    kind,
    title: id,
    price: { amount, currency },
    price_is_estimate: false,
    source_url: `https://example.com/${id}`,
    fetched_at: "2026-11-21T00:00:00Z",
  };
}

const options = [
  option("flight", "flight", 1400),
  option("hotel", "hotel", 700),
  option("temple", "activity", 0),
  option("tea", "activity", 45),
  option("fuji", "activity", 140),
  option("sushi", "food", 85),
];
const index = indexOptions(options);

const plan: Plan = {
  id: "p1",
  trip_id: "t1",
  title: "Temples and history",
  summary: "",
  flight_option_id: "flight",
  hotel_option_id: "hotel",
  days: [
    { day: 1, items: [{ option_id: "temple", locked: false }] },
    { day: 2, items: [{ option_id: "tea", locked: false }] },
    { day: 3, items: [] },
  ],
  cost_breakdown: [],
  // 1400 + 700 + 0 + 45 = 2145, plus 375 of meals/transport not tied to an option.
  total: usd(2520),
  budget: usd(5000),
  warnings: [],
  saved: true,
};

describe("runningTotal", () => {
  test("matches the planner's total before any edits", () => {
    const t = runningTotal(plan, plan, index);
    expect(t.total).toEqual(usd(2520));
    expect(t.otherCosts).toEqual(usd(375));
    expect(t.complete).toBe(true);
    expect(t.breakdown).toEqual([
      { category: "flight", total: usd(1400) },
      { category: "hotel", total: usd(700) },
      { category: "activity", total: usd(45) },
      { category: "other", total: usd(375) },
    ]);
  });

  test("follows edits and keeps costs that aren't options", () => {
    const edited = addItem(removeItem(plan, 2, 0), "fuji", 3);
    expect(runningTotal(plan, edited, index).total).toEqual(usd(2520 - 45 + 140));
  });

  test("never goes below the option prices when the planner's total is too low", () => {
    const low = { ...plan, total: usd(100) };
    const t = runningTotal(low, low, index);
    expect(t.otherCosts).toEqual(usd(0));
    expect(t.total).toEqual(usd(2145));
  });

  test("is marked incomplete when a price is missing or in another currency", () => {
    const missing = addItem(plan, "unknown", 1);
    expect(runningTotal(plan, missing, index).complete).toBe(false);

    const yen = indexOptions([...options, option("ramen", "food", 1500, "JPY")]);
    expect(runningTotal(plan, addItem(plan, "ramen", 1), yen).complete).toBe(false);
  });
});

describe("edits", () => {
  test("don't mutate the original and mark the plan unsaved", () => {
    const before = JSON.stringify(plan);
    const next = removeItem(plan, 1, 0);
    expect(JSON.stringify(plan)).toBe(before);
    expect(next.saved).toBe(false);
    expect(next.days[0].items).toEqual([]);
  });

  test("moving an item locks it and puts it on the new day", () => {
    const next = moveItem(plan, 2, 0, 1);
    expect(next.days[0].items).toEqual([
      { option_id: "temple", locked: false },
      { option_id: "tea", locked: true },
    ]);
    expect(next.days[1].items).toEqual([]);
  });

  test("moving to the same day does nothing", () => {
    expect(moveItem(plan, 1, 0, 1)).toBe(plan);
  });

  test("added items are locked", () => {
    expect(addItem(plan, "fuji", 3).days[2].items).toEqual([{ option_id: "fuji", locked: true }]);
  });

  test("toggleLock flips one item", () => {
    expect(toggleLock(plan, 1, 0).days[0].items[0].locked).toBe(true);
  });

  test("addableOptions leaves out flights, hotels and what's already planned", () => {
    expect(addableOptions(plan, options).map((o) => o.id)).toEqual(["fuji", "sushi"]);
  });
});

test("isOverBudget", () => {
  expect(isOverBudget(usd(5000), usd(5000))).toBe(false);
  expect(isOverBudget(usd(5000.01), usd(5000))).toBe(true);
});
