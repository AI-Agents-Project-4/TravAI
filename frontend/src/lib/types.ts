// Types for API data. These mirror docs/api-contract.md (DRAFT). If a shape
// changes, update the contract in the same PR.

export type Money = { amount: number; currency: string };

export type OptionKind = "flight" | "hotel" | "activity" | "transport" | "food";

/** One researched thing the planner can use. Written by the research agent. */
export type Option = {
  id: string;
  kind: OptionKind;
  title: string;
  description?: string;
  /** Total for the whole party, taxes and fees included. */
  price: Money;
  /** True if there was no exact quote (then it's rounded up). */
  price_is_estimate: boolean;
  source_url: string;
  fetched_at: string;
  location?: { name: string; lat?: number; lng?: number };
  duration_minutes?: number;
  opening_hours?: string;
  details?: Record<string, unknown>;
};

export type ScheduledItem = {
  option_id: string;
  start_time?: string;
  end_time?: string;
  /** True = the user placed it, so a redraft must keep it. */
  locked: boolean;
};

export type Day = { day: number; date?: string; items: ScheduledItem[] };

export type WarningKind = "safety" | "stale_data" | "estimate" | "over_budget";

export type Warning = {
  kind: WarningKind;
  message: string;
  source_url?: string;
};

export type CostCategory = OptionKind | "other";

export type Plan = {
  id: string;
  trip_id: string;
  title: string;
  summary: string;
  flight_option_id?: string;
  hotel_option_id?: string;
  days: Day[];
  cost_breakdown: { category: CostCategory; total: Money }[];
  total: Money;
  budget: Money;
  warnings: Warning[];
  saved: boolean;
};

export type TransportMode = "fly" | "drive";

/** Body of `POST /trips`. */
export type TripRequest = {
  origin: string;
  destination: string;
  /** null = flexible dates (the eval cases leave it unset). */
  start_date: string | null;
  duration_days: number;
  travelers: number;
  budget: Money;
  transport_mode: TransportMode;
  end_destination: string | null;
};

export type CreateTripResponse = { trip_id: string; warnings: Warning[] };

export type TripStatus = "researching" | "planning" | "done" | "failed";

export type TripProgress = {
  status: TripStatus;
  steps: { message: string; at: string }[];
};

export type PlansResponse =
  | { feasible: true; plans: Plan[]; options: Option[] }
  | { feasible: false; reason: string; min_estimated_cost: Money };

/** Body of `POST /plans/{plan_id}/redraft`. */
export type RedraftRequest = { days: Day[]; removed_option_ids: string[] };

export type DroppedItem = { option_id: string; reason: string };

export type RedraftResponse = { plan: Plan; dropped_items: DroppedItem[] };
