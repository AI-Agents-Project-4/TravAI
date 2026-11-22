// The mock stands in for the backend while the UI is built, so check that it
// acts out the product rules the UI has to handle.
import { describe, expect, test } from "vitest";
import type { Plan, TripRequest } from "../types";
import { createMockApi, memoryStore } from "./mock";

function setup() {
  let t = Date.parse("2026-11-21T12:00:00Z");
  let n = 0;
  const api = createMockApi({
    store: memoryStore(),
    now: () => t,
    delayMs: 0,
    stepMs: 10,
    newId: () => `trip${++n}`,
  });
  return { api, advance: (ms: number) => (t += ms) };
}

const trip = (overrides: Partial<TripRequest>): TripRequest => ({
  origin: "DEN",
  destination: "Tokyo, Japan",
  start_date: null,
  duration_days: 5,
  travelers: 1,
  budget: { amount: 5000, currency: "USD" },
  transport_mode: "fly",
  end_destination: null,
  ...overrides,
});

async function finished(overrides: Partial<TripRequest>) {
  const s = setup();
  const { trip_id } = await s.api.createTrip(trip(overrides));
  s.advance(1000);
  return { ...s, tripId: trip_id, result: await s.api.getPlans(trip_id) };
}

describe("mock API", () => {
  test("Tokyo, 5 days, $5,000: three plans at or under budget, all sourced", async () => {
    const { result } = await finished({});
    expect(result.feasible).toBe(true);
    if (!result.feasible) return;
    expect(result.plans).toHaveLength(3);
    expect(new Set(result.plans.map((p) => p.title)).size).toBe(3);
    // The plans differ in what they schedule, and each leaves options to add.
    const scheduled = result.plans.map((p) => p.days.flatMap((d) => d.items.map((i) => i.option_id)).sort().join());
    expect(new Set(scheduled).size).toBe(3);
    const activities = result.options.filter((o) => o.kind !== "flight" && o.kind !== "hotel").length;
    for (const plan of result.plans) {
      const count = plan.days.reduce((n, d) => n + d.items.length, 0);
      expect(count).toBeLessThan(activities);
      expect(plan.days.every((d) => d.items.length > 0)).toBe(true);
    }
    for (const plan of result.plans) {
      expect(plan.total.amount).toBeLessThanOrEqual(5000);
      expect(plan.flight_option_id).toBeDefined();
      expect(plan.hotel_option_id).toBeDefined();
      expect(plan.days).toHaveLength(5);
    }
    for (const o of result.options) {
      expect(o.source_url).toMatch(/^https:\/\/example\.com\//);
      expect(Number.isNaN(Date.parse(o.fetched_at))).toBe(false);
    }
  });

  test("Japan, 30 days, $500: honestly not feasible, with a minimum cost above the budget", async () => {
    const { result } = await finished({ destination: "Japan", duration_days: 30, budget: { amount: 500, currency: "USD" } });
    expect(result.feasible).toBe(false);
    if (result.feasible) return;
    expect(result.min_estimated_cost.amount).toBeGreaterThan(500);
  });

  test("Colorado Springs drive day trip: no flight or hotel", async () => {
    const { result } = await finished({
      destination: "Colorado Springs, CO",
      duration_days: 1,
      transport_mode: "drive",
      budget: { amount: 500, currency: "USD" },
    });
    expect(result.feasible).toBe(true);
    if (!result.feasible) return;
    expect(result.plans[0].flight_option_id).toBeUndefined();
    expect(result.plans[0].hotel_option_id).toBeUndefined();
  });

  test("Ukraine: safety warning first, and research waits for the user to proceed", async () => {
    const { api, advance } = setup();
    const created = await api.createTrip(trip({ destination: "Kyiv, Ukraine", duration_days: 3, budget: { amount: 1000, currency: "USD" } }));
    expect(created.warnings.map((w) => w.kind)).toContain("safety");

    advance(1000);
    expect((await api.getProgress(created.trip_id)).steps).toEqual([]);

    await api.proceedTrip(created.trip_id);
    advance(1000);
    expect((await api.getProgress(created.trip_id)).status).toBe("done");
    const result = await api.getPlans(created.trip_id);
    expect(result.feasible).toBe(true);
    if (result.feasible) expect(result.plans[0].warnings.map((w) => w.kind)).toContain("safety");
  });

  test("progress moves from researching to planning to done", async () => {
    const { api, advance } = setup();
    const { trip_id } = await api.createTrip(trip({}));
    expect((await api.getProgress(trip_id)).status).toBe("researching");
    await expect(api.getPlans(trip_id)).rejects.toThrow(/aren't ready/);
    advance(45);
    expect((await api.getProgress(trip_id)).status).toBe("planning");
    advance(100);
    expect((await api.getProgress(trip_id)).status).toBe("done");
  });

  test("redraft keeps locked items and drops unlocked ones, most expensive first", async () => {
    // Tokyo, 5 days, 1 traveler: flight 1450 + hotel 740 + meals/transport 375 = 2565 fixed.
    const { api, result } = await finished({ budget: { amount: 3000, currency: "USD" } });
    if (!result.feasible) throw new Error("expected feasible");
    const byTitle = (prefix: string) => result.options.find((o) => o.title.startsWith(prefix))!.id;
    const fuji = byTitle("Mount Fuji"); // 140, locked
    const hakone = byTitle("Hakone"); // 130
    const izakaya = byTitle("Shinjuku izakaya"); // 120
    const tsukiji = byTitle("Tsukiji"); // 95
    const days: Plan["days"] = [
      {
        day: 1,
        items: [
          { option_id: fuji, locked: true },
          { option_id: hakone, locked: false },
          { option_id: izakaya, locked: false },
          { option_id: tsukiji, locked: false },
        ],
      },
      ...[2, 3, 4, 5].map((day) => ({ day, items: [] })),
    ];

    // 2565 + 140 + 130 + 120 + 95 = 3050 > 3000, so dropping Hakone (130) fits.
    const { plan, dropped_items } = await api.redraftPlan(result.plans[0].id, { days, removed_option_ids: [] });

    expect(dropped_items.map((d) => d.option_id)).toEqual([hakone]);
    expect(dropped_items[0].reason).toMatch(/budget/);
    expect(plan.days[0].items.map((i) => i.option_id)).toEqual([fuji, izakaya, tsukiji]);
    expect(plan.total.amount).toBe(2920);
  });

  test("redraft never drops locked items, and warns when they alone go over", async () => {
    const { api, result } = await finished({ budget: { amount: 2600, currency: "USD" } });
    if (!result.feasible) throw new Error("expected feasible");
    const fuji = result.options.find((o) => o.title.startsWith("Mount Fuji"))!.id;
    const days: Plan["days"] = [1, 2, 3, 4, 5].map((day) => ({
      day,
      items: day === 1 ? [{ option_id: fuji, locked: true }] : [],
    }));
    const { plan, dropped_items } = await api.redraftPlan(result.plans[0].id, { days, removed_option_ids: [] });
    expect(dropped_items).toEqual([]);
    expect(plan.days[0].items[0].option_id).toBe(fuji);
    expect(plan.warnings.map((w) => w.kind)).toContain("over_budget");
  });

  test("redraft leaves out items the user removed", async () => {
    const { api, result } = await finished({});
    if (!result.feasible) throw new Error("expected feasible");
    const plan = result.plans[0];
    const removed = plan.days[0].items[0].option_id;
    const { plan: next } = await api.redraftPlan(plan.id, { days: plan.days, removed_option_ids: [removed] });
    expect(next.days.flatMap((d) => d.items.map((i) => i.option_id))).not.toContain(removed);
  });

  test("save and come back later", async () => {
    const { api, result } = await finished({});
    if (!result.feasible) throw new Error("expected feasible");
    const saved = await api.savePlan(result.plans[1]);
    expect(saved.saved).toBe(true);
    expect((await api.getPlan(saved.id)).saved).toBe(true);
  });
});
