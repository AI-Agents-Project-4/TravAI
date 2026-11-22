import { describe, expect, test } from "vitest";
import { EMPTY_TRIP_FORM, parseTripForm, type TripFormValues } from "./trip-form";

const today = new Date("2026-11-21T10:00:00");
const tokyo: TripFormValues = {
  ...EMPTY_TRIP_FORM,
  origin: " DEN ",
  destination: "Tokyo, Japan",
  duration_days: "5",
  travelers: "1",
  budget: "5,000",
};

describe("parseTripForm", () => {
  test("builds the POST /trips body (eval case 1)", () => {
    expect(parseTripForm(tokyo, today)).toEqual({
      ok: true,
      request: {
        origin: "DEN",
        destination: "Tokyo, Japan",
        start_date: null,
        duration_days: 5,
        travelers: 1,
        budget: { amount: 5000, currency: "USD" },
        transport_mode: "fly",
        end_destination: null,
      },
    });
  });

  test("drive trips and multi-stop trips", () => {
    const result = parseTripForm(
      { ...tokyo, transport_mode: "drive", destination: "Paris", end_destination: "Rome", start_date: "2027-03-10" },
      today,
    );
    expect(result.ok && result.request).toMatchObject({
      transport_mode: "drive",
      end_destination: "Rome",
      start_date: "2027-03-10",
    });
  });

  test("reports every missing or bad field", () => {
    const result = parseTripForm(
      { ...EMPTY_TRIP_FORM, duration_days: "0", travelers: "1.5", budget: "abc" },
      today,
    );
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(Object.keys(result.errors).sort()).toEqual(
      ["budget", "destination", "duration_days", "origin", "travelers"].sort(),
    );
  });

  test("rejects a start date in the past but allows today", () => {
    expect(parseTripForm({ ...tokyo, start_date: "2026-11-20" }, today).ok).toBe(false);
    expect(parseTripForm({ ...tokyo, start_date: "2026-11-21" }, today).ok).toBe(true);
  });

  test("rejects zero or negative budgets", () => {
    expect(parseTripForm({ ...tokyo, budget: "0" }, today).ok).toBe(false);
    expect(parseTripForm({ ...tokyo, budget: "-5" }, today).ok).toBe(false);
    expect(parseTripForm({ ...tokyo, budget: "499.99" }, today).ok).toBe(true);
  });
});
