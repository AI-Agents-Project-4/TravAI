// In-browser stand-in for the backend, used while the real endpoints are being
// built (NEXT_PUBLIC_API_MOCK=true). It follows docs/api-contract.md and acts
// out the product rules so the UI can be built and tested against them:
// honest "not feasible" answers, safety warnings first, locked items survive
// a redraft. Its prices are made up; the UI shows a "demo data" banner.
import type {
  CostCategory,
  CreateTripResponse,
  Day,
  DroppedItem,
  Option,
  Plan,
  PlansResponse,
  ScheduledItem,
  TripProgress,
  TripRequest,
  Warning,
} from "../types";
import { formatMoney } from "../format";
import { ApiError, type TravaiApi } from "./client";
import { mockResearch, type MockResearch } from "./mock-data";

type MockTrip = {
  id: string;
  request: TripRequest;
  createdAt: number;
  /** When research started. null while waiting for the safety confirmation. */
  startedAt: number | null;
  warnings: Warning[];
};

type MockState = { trips: Record<string, MockTrip>; plans: Record<string, Plan> };

type Store = { load(): MockState; save(state: MockState): void };

const STORAGE_KEY = "travai-mock-api-v1";

/** sessionStorage so a page reload keeps the trip; memory if that fails. */
function browserStore(): Store {
  let memory: MockState = { trips: {}, plans: {} };
  return {
    load() {
      try {
        const raw = globalThis.sessionStorage?.getItem(STORAGE_KEY);
        if (raw) memory = JSON.parse(raw) as MockState;
      } catch {
        // Storage blocked or corrupt; keep the in-memory copy.
      }
      return memory;
    },
    save(state) {
      memory = state;
      try {
        globalThis.sessionStorage?.setItem(STORAGE_KEY, JSON.stringify(state));
      } catch {
        // Ignore; memory still has it.
      }
    },
  };
}

export function memoryStore(): Store {
  let state: MockState = { trips: {}, plans: {} };
  return {
    load: () => state,
    save: (s) => {
      state = s;
    },
  };
}

export type MockApiOptions = {
  store?: Store;
  now?: () => number;
  /** Simulated network latency. */
  delayMs?: number;
  /** Time between simulated research steps. */
  stepMs?: number;
  newId?: () => string;
};

const DAY_MINUTES = 600; // 9:00 to 19:00

function clockTime(minutesAfterNine: number): string {
  const total = 9 * 60 + minutesAfterNine;
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

/** Fills in start/end times one after another, with 30 minutes between items. */
function scheduleTimes(items: ScheduledItem[], options: Map<string, Option>): ScheduledItem[] {
  let t = 0;
  return items.map((item) => {
    const minutes = options.get(item.option_id)?.duration_minutes ?? 90;
    const timed = { ...item, start_time: clockTime(t), end_time: clockTime(t + minutes) };
    t += minutes + 30;
    return timed;
  });
}

function itemIds(days: Day[]): string[] {
  return days.flatMap((d) => d.items.map((i) => i.option_id));
}

function priceOf(options: Map<string, Option>, id: string): number {
  return options.get(id)?.price.amount ?? 0;
}

function fixedCost(r: MockResearch, options: Map<string, Option>): number {
  return (
    (r.flightId ? priceOf(options, r.flightId) : 0) +
    (r.hotelId ? priceOf(options, r.hotelId) : 0) +
    r.otherCosts
  );
}

function totalFor(days: Day[], r: MockResearch, options: Map<string, Option>): number {
  return fixedCost(r, options) + itemIds(days).reduce((sum, id) => sum + priceOf(options, id), 0);
}

/**
 * Drops unlocked items, most expensive first, until the plan fits the budget.
 * Locked items are never dropped (product rule 5).
 */
function fitToBudget(
  days: Day[],
  budget: number,
  r: MockResearch,
  options: Map<string, Option>,
): { days: Day[]; dropped: DroppedItem[] } {
  const current = days.map((d) => ({ ...d, items: [...d.items] }));
  const dropped: DroppedItem[] = [];
  const currency = options.values().next().value?.price.currency ?? "USD";
  while (totalFor(current, r, options) > budget) {
    let best: { day: Day; index: number; price: number } | null = null;
    for (const day of current) {
      for (const [index, item] of day.items.entries()) {
        const price = priceOf(options, item.option_id);
        if (!item.locked && price > 0 && (!best || price > best.price)) best = { day, index, price };
      }
    }
    if (!best) break;
    const [removed] = best.day.items.splice(best.index, 1);
    dropped.push({
      option_id: removed.option_id,
      reason: `Dropped to stay under your budget (saves ${formatMoney({ amount: best.price, currency })}).`,
    });
  }
  return { days: current, dropped };
}

function buildPlan(
  trip: MockTrip,
  r: MockResearch,
  options: Map<string, Option>,
  planId: string,
  days: Day[],
): Plan {
  const currency = trip.request.budget.currency;
  const byCategory = new Map<CostCategory, number>();
  const add = (c: CostCategory, amount: number) => byCategory.set(c, (byCategory.get(c) ?? 0) + amount);
  if (r.flightId) add("flight", priceOf(options, r.flightId));
  if (r.hotelId) add("hotel", priceOf(options, r.hotelId));
  for (const id of itemIds(days)) add(options.get(id)!.kind, priceOf(options, id));
  add("other", r.otherCosts);
  const total = totalFor(days, r, options);

  const warnings: Warning[] = [];
  if (r.safety) warnings.push({ kind: "safety", message: r.safety });
  const ids = [r.flightId, r.hotelId, ...itemIds(days)].filter(Boolean) as string[];
  if (ids.some((id) => options.get(id)?.price_is_estimate)) {
    warnings.push({ kind: "estimate", message: "Some prices are estimates and were rounded up." });
  }
  if (total > trip.request.budget.amount) {
    warnings.push({
      kind: "over_budget",
      message: "Your locked items alone go over the budget. Unlock or remove something to fit.",
    });
  }

  return {
    id: planId,
    trip_id: trip.id,
    title: "",
    summary: "",
    flight_option_id: r.flightId,
    hotel_option_id: r.hotelId,
    days: days.map((d) => ({ ...d, items: scheduleTimes(d.items, options) })),
    cost_breakdown: [...byCategory].map(([category, amount]) => ({
      category,
      total: { amount, currency },
    })),
    total: { amount: total, currency },
    budget: trip.request.budget,
    warnings,
    saved: false,
  };
}

/** Spreads a theme's activities over the days, at most a day's worth each. */
function draftDays(trip: MockTrip, r: MockResearch, options: Map<string, Option>, theme: 0 | 1 | 2): Day[] {
  const order = [...r.byTheme[theme], ...r.byTheme[(theme + 1) % 3], ...r.byTheme[(theme + 2) % 3]];
  const queue = [...order];
  const days: Day[] = [];
  for (let day = 1; day <= trip.request.duration_days; day++) {
    const items: ScheduledItem[] = [];
    let minutes = 0;
    if (day === 1 && r.driveId) {
      items.push({ option_id: r.driveId, locked: false });
      minutes += (options.get(r.driveId)?.duration_minutes ?? 90) + 30;
    }
    for (let i = 0; i < queue.length && items.length < 3; ) {
      const m = options.get(queue[i])?.duration_minutes ?? 90;
      if (minutes + m <= DAY_MINUTES) {
        items.push({ option_id: queue[i], locked: false });
        minutes += m + 30;
        queue.splice(i, 1);
      } else i++;
    }
    days.push({ day, items });
  }
  return days;
}

const SUMMARIES = [
  "Leans on landmarks and history, with a slower pace.",
  "Built around eating well and evenings out.",
  "Uses the city as a base for trips out of town.",
];

export function createMockApi(opts: MockApiOptions = {}): TravaiApi {
  const store = opts.store ?? browserStore();
  const now = opts.now ?? (() => Date.now());
  const delayMs = opts.delayMs ?? 250;
  const stepMs = opts.stepMs ?? 1200;
  const newId = opts.newId ?? (() => globalThis.crypto.randomUUID());

  const wait = <T>(value: T) =>
    delayMs > 0 ? new Promise<T>((resolve) => setTimeout(() => resolve(value), delayMs)) : Promise.resolve(value);

  function getTrip(state: MockState, tripId: string): MockTrip {
    const trip = state.trips[tripId];
    if (!trip) throw new ApiError("Trip not found.", 404);
    return trip;
  }

  function research(trip: MockTrip) {
    const r = mockResearch(trip.id, trip.request, new Date(trip.startedAt ?? trip.createdAt).toISOString());
    return { r, options: new Map(r.options.map((o) => [o.id, o])) };
  }

  function progressOf(trip: MockTrip): TripProgress {
    if (trip.startedAt === null) return { status: "researching", steps: [] };
    const { r } = research(trip);
    const counts = {
      activities: r.byTheme.flat().length,
    };
    const to = trip.request.destination;
    const script: [TripProgress["status"], string][] = [
      ["researching", trip.request.transport_mode === "fly" ? `Searching flights to ${to}` : `Planning the drive to ${to}`],
      ["researching", trip.request.transport_mode === "fly" ? "Found 4 flights, checking hotel prices" : "Checking hotel prices"],
      ["researching", `Found 6 hotels, searching activities in ${to}`],
      ["researching", `Found ${counts.activities} activities`],
      ["planning", "Building three itineraries"],
      ["done", "Done"],
    ];
    const elapsed = now() - trip.startedAt;
    const reached = Math.min(script.length, Math.floor(elapsed / stepMs) + 1);
    const steps = script.slice(0, reached).map(([, message], i) => ({
      message,
      at: new Date(trip.startedAt! + i * stepMs).toISOString(),
    }));
    return { status: script[reached - 1][0], steps };
  }

  return {
    async createTrip(request): Promise<CreateTripResponse> {
      const state = store.load();
      const id = newId();
      const r = mockResearch(id, request, new Date(now()).toISOString());
      const warnings: Warning[] = r.safety ? [{ kind: "safety", message: r.safety }] : [];
      const trip: MockTrip = {
        id,
        request,
        createdAt: now(),
        startedAt: warnings.length ? null : now(),
        warnings,
      };
      store.save({ ...state, trips: { ...state.trips, [id]: trip } });
      return wait({ trip_id: id, warnings });
    },

    async proceedTrip(tripId) {
      const state = store.load();
      const trip = getTrip(state, tripId);
      if (trip.startedAt === null) {
        store.save({ ...state, trips: { ...state.trips, [tripId]: { ...trip, startedAt: now() } } });
      }
      return wait(undefined);
    },

    async getProgress(tripId) {
      return wait(progressOf(getTrip(store.load(), tripId)));
    },

    async getPlans(tripId): Promise<PlansResponse> {
      const state = store.load();
      const trip = getTrip(state, tripId);
      if (progressOf(trip).status !== "done") throw new ApiError("Plans aren't ready yet.", 409);
      const { r, options } = research(trip);
      const budget = trip.request.budget;

      const minCost = fixedCost(r, options);
      if (minCost > budget.amount) {
        // Round the minimum up to the next 50 so it's never an underestimate.
        const rounded = Math.ceil(minCost / 50) * 50;
        return wait({
          feasible: false,
          reason: `Flights, a place to stay, meals and local transport for ${trip.request.duration_days} days come to at least ${formatMoney({ amount: rounded, currency: budget.currency })} before any activities. That's more than your ${formatMoney(budget)} budget.`,
          min_estimated_cost: { amount: rounded, currency: budget.currency },
        });
      }

      let plans = Object.values(state.plans).filter((p) => p.trip_id === tripId);
      if (plans.length === 0) {
        plans = ([0, 1, 2] as const).map((theme) => {
          const fitted = fitToBudget(draftDays(trip, r, options, theme), budget.amount, r, options);
          const plan = buildPlan(trip, r, options, `${tripId}-plan-${theme}`, fitted.days);
          return { ...plan, title: r.themes[theme], summary: SUMMARIES[theme] };
        });
        const next = { ...state.plans };
        for (const p of plans) next[p.id] = p;
        store.save({ ...state, plans: next });
      }
      return wait({ feasible: true, plans, options: r.options });
    },

    async redraftPlan(planId, request) {
      const state = store.load();
      const plan = state.plans[planId];
      if (!plan) throw new ApiError("Plan not found.", 404);
      const trip = getTrip(state, plan.trip_id);
      const { r, options } = research(trip);
      const removed = new Set(request.removed_option_ids);
      const days = request.days.map((d) => ({
        ...d,
        items: d.items.filter((i) => !removed.has(i.option_id) && options.has(i.option_id)),
      }));
      const fitted = fitToBudget(days, trip.request.budget.amount, r, options);
      const next: Plan = {
        ...buildPlan(trip, r, options, planId, fitted.days),
        title: plan.title,
        summary: plan.summary,
      };
      store.save({ ...state, plans: { ...state.plans, [planId]: next } });
      return wait({ plan: next, dropped_items: fitted.dropped });
    },

    async savePlan(plan) {
      const state = store.load();
      if (!state.plans[plan.id]) throw new ApiError("Plan not found.", 404);
      const saved = { ...plan, saved: true };
      store.save({ ...state, plans: { ...state.plans, [plan.id]: saved } });
      return wait(saved);
    },

    async getPlan(planId) {
      const plan = store.load().plans[planId];
      if (!plan) throw new ApiError("Plan not found.", 404);
      return wait(plan);
    },
  };
}
