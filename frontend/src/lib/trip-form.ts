import type { TransportMode, TripRequest } from "./types";

/** Raw form values, as strings straight from the inputs. */
export type TripFormValues = {
  origin: string;
  destination: string;
  start_date: string;
  duration_days: string;
  travelers: string;
  budget: string;
  currency: string;
  transport_mode: TransportMode;
  end_destination: string;
};

export const EMPTY_TRIP_FORM: TripFormValues = {
  origin: "",
  destination: "",
  start_date: "",
  duration_days: "5",
  travelers: "1",
  budget: "",
  currency: "USD",
  transport_mode: "fly",
  end_destination: "",
};

export const CURRENCIES = ["USD", "EUR", "GBP", "JPY", "CAD", "MXN"] as const;

export const LIMITS = {
  maxDays: 60,
  maxTravelers: 20,
} as const;

export type TripFormErrors = Partial<Record<keyof TripFormValues, string>>;

function wholeNumber(value: string): number | null {
  if (!/^\d+$/.test(value.trim())) return null;
  return Number(value.trim());
}

/** Validates the form. Returns the request to send, or the errors to show. */
export function parseTripForm(
  values: TripFormValues,
  today: Date = new Date(),
): { ok: true; request: TripRequest } | { ok: false; errors: TripFormErrors } {
  const errors: TripFormErrors = {};
  const origin = values.origin.trim();
  const destination = values.destination.trim();
  const endDestination = values.end_destination.trim();

  if (!origin) {
    errors.origin =
      values.transport_mode === "fly"
        ? "Enter where you're flying from (an airport or city)."
        : "Enter where you're driving from.";
  }
  if (!destination) errors.destination = "Enter where you want to go.";

  if (values.start_date) {
    const start = new Date(`${values.start_date}T00:00:00`);
    const midnight = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    if (Number.isNaN(start.getTime())) errors.start_date = "Enter a valid date.";
    else if (start < midnight) errors.start_date = "The start date is in the past.";
  }

  const days = wholeNumber(values.duration_days);
  if (days === null || days < 1 || days > LIMITS.maxDays) {
    errors.duration_days = `Enter a number of days from 1 to ${LIMITS.maxDays}.`;
  }

  const travelers = wholeNumber(values.travelers);
  if (travelers === null || travelers < 1 || travelers > LIMITS.maxTravelers) {
    errors.travelers = `Enter from 1 to ${LIMITS.maxTravelers} travelers.`;
  }

  const budgetText = values.budget.replace(/[,\s]/g, "");
  const budget = /^\d+(\.\d{1,2})?$/.test(budgetText) ? Number(budgetText) : NaN;
  if (!(budget > 0)) errors.budget = "Enter your total budget as a number, like 5000.";

  if (Object.keys(errors).length > 0) return { ok: false, errors };

  return {
    ok: true,
    request: {
      origin,
      destination,
      start_date: values.start_date || null,
      duration_days: days!,
      travelers: travelers!,
      budget: { amount: budget, currency: values.currency },
      transport_mode: values.transport_mode,
      end_destination: endDestination || null,
    },
  };
}
