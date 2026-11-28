import type { CostCategory, Day, Money, Option, Plan, ScheduledItem } from "./types";

export type OptionIndex = ReadonlyMap<string, Option>;

export function indexOptions(options: Option[]): OptionIndex {
  return new Map(options.map((o) => [o.id, o]));
}

/** Every option a plan pays for: flight, hotel and each scheduled item. */
export function planOptionIds(plan: Plan): string[] {
  const ids: string[] = [];
  if (plan.flight_option_id) ids.push(plan.flight_option_id);
  if (plan.hotel_option_id) ids.push(plan.hotel_option_id);
  for (const day of plan.days) for (const item of day.items) ids.push(item.option_id);
  return ids;
}

type OptionSum = {
  amount: number;
  byCategory: Map<CostCategory, number>;
  /** Option ids the plan refers to but we have no price for. */
  missing: string[];
  /** Options priced in a currency other than the budget's. */
  otherCurrency: string[];
};

function sumOptions(plan: Plan, index: OptionIndex): OptionSum {
  const currency = plan.budget.currency;
  const byCategory = new Map<CostCategory, number>();
  const missing: string[] = [];
  const otherCurrency: string[] = [];
  let amount = 0;
  for (const id of planOptionIds(plan)) {
    const option = index.get(id);
    if (!option) {
      missing.push(id);
      continue;
    }
    if (option.price.currency !== currency) {
      otherCurrency.push(id);
      continue;
    }
    amount += option.price.amount;
    byCategory.set(option.kind, (byCategory.get(option.kind) ?? 0) + option.price.amount);
  }
  return { amount, byCategory, missing, otherCurrency };
}

export type RunningTotal = {
  total: Money;
  breakdown: { category: CostCategory; total: Money }[];
  /**
   * Costs in the planner's total that aren't tied to an option (fees, local
   * transport...). Carried over unchanged so editing never makes the total
   * smaller than what the planner counted.
   */
  otherCosts: Money;
  /**
   * False when some price is missing or in another currency. The total is
   * then incomplete and the UI must say so instead of showing a low number.
   */
  complete: boolean;
};

/**
 * Client-side running total for the plan editor.
 *
 * `base` is the plan as the backend last returned it, `edited` is the user's
 * current version. Total = option prices in `edited` + whatever part of the
 * backend's total isn't explained by option prices in `base` (never negative).
 */
export function runningTotal(base: Plan, edited: Plan, index: OptionIndex): RunningTotal {
  const currency = edited.budget.currency;
  const baseSum = sumOptions(base, index);
  const otherCostsAmount =
    base.total.currency === currency ? Math.max(0, base.total.amount - baseSum.amount) : 0;
  const editedSum = sumOptions(edited, index);

  const order: CostCategory[] = ["flight", "hotel", "transport", "activity", "food", "other"];
  const byCategory = new Map(editedSum.byCategory);
  if (otherCostsAmount > 0) {
    byCategory.set("other", (byCategory.get("other") ?? 0) + otherCostsAmount);
  }
  const breakdown = order
    .filter((c) => byCategory.has(c))
    .map((category) => ({ category, total: { amount: byCategory.get(category)!, currency } }));

  return {
    total: { amount: editedSum.amount + otherCostsAmount, currency },
    breakdown,
    otherCosts: { amount: otherCostsAmount, currency },
    complete:
      editedSum.missing.length === 0 &&
      editedSum.otherCurrency.length === 0 &&
      base.total.currency === currency,
  };
}

export function isOverBudget(total: Money, budget: Money): boolean {
  return total.currency === budget.currency && total.amount > budget.amount;
}

// ---- Edits. All return a new plan; the input is never mutated. ----------

function mapDays(plan: Plan, fn: (day: Day) => Day): Plan {
  return { ...plan, days: plan.days.map(fn), saved: false };
}

export function removeItem(plan: Plan, dayNumber: number, index: number): Plan {
  return mapDays(plan, (d) =>
    d.day === dayNumber ? { ...d, items: d.items.filter((_, i) => i !== index) } : d,
  );
}

/** Moves an item to the end of another day. A moved item is locked. */
export function moveItem(plan: Plan, fromDay: number, index: number, toDay: number): Plan {
  if (fromDay === toDay) return plan;
  const item = plan.days.find((d) => d.day === fromDay)?.items[index];
  if (!item) return plan;
  const moved: ScheduledItem = { option_id: item.option_id, locked: true };
  return mapDays(plan, (d) => {
    if (d.day === fromDay) return { ...d, items: d.items.filter((_, i) => i !== index) };
    if (d.day === toDay) return { ...d, items: [...d.items, moved] };
    return d;
  });
}

/** Adds an option to a day. An added item is locked. */
export function addItem(plan: Plan, optionId: string, toDay: number): Plan {
  return mapDays(plan, (d) =>
    d.day === toDay ? { ...d, items: [...d.items, { option_id: optionId, locked: true }] } : d,
  );
}

export function toggleLock(plan: Plan, dayNumber: number, index: number): Plan {
  return mapDays(plan, (d) =>
    d.day === dayNumber
      ? { ...d, items: d.items.map((it, i) => (i === index ? { ...it, locked: !it.locked } : it)) }
      : d,
  );
}

/** Options the user can still add: not flights/hotels, not already scheduled. */
export function addableOptions(plan: Plan, options: Option[]): Option[] {
  const used = new Set(planOptionIds(plan));
  return options.filter((o) => o.kind !== "flight" && o.kind !== "hotel" && !used.has(o.id));
}
