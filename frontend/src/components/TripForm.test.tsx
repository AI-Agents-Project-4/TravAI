import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { TripForm } from "./TripForm";

const { push, api } = vi.hoisted(() => ({
  push: vi.fn(),
  api: { createTrip: vi.fn(), proceedTrip: vi.fn() },
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/api", () => ({ api }));

beforeEach(() => {
  push.mockReset();
  api.createTrip.mockReset();
  api.proceedTrip.mockReset();
});

function fill(label: RegExp, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

function fillTokyo() {
  fill(/flying from/i, "DEN");
  fill(/^destination/i, "Tokyo, Japan");
  fill(/^days/i, "5");
  fill(/total budget/i, "5000");
}

const submit = () => fireEvent.click(screen.getByRole("button", { name: "Plan my trip" }));

describe("TripForm", () => {
  test("shows errors and doesn't call the API when fields are missing", () => {
    render(<TripForm />);
    submit();
    expect(screen.getByText(/where you're flying from/i)).toBeDefined();
    expect(screen.getByText(/where you want to go/i)).toBeDefined();
    expect(screen.getByLabelText(/^destination/i).getAttribute("aria-invalid")).toBe("true");
    expect(api.createTrip).not.toHaveBeenCalled();
  });

  test("sends the trip and goes to the progress page", async () => {
    api.createTrip.mockResolvedValue({ trip_id: "t1", warnings: [] });
    render(<TripForm />);
    fillTokyo();
    submit();
    await waitFor(() => expect(push).toHaveBeenCalledWith("/trips/t1"));
    expect(api.createTrip).toHaveBeenCalledWith({
      origin: "DEN",
      destination: "Tokyo, Japan",
      start_date: null,
      duration_days: 5,
      travelers: 1,
      budget: { amount: 5000, currency: "USD" },
      transport_mode: "fly",
      end_destination: null,
    });
  });

  test("drive trips ask where you're driving from", () => {
    render(<TripForm />);
    fireEvent.click(screen.getByRole("radio", { name: "Drive" }));
    expect(screen.getByLabelText(/driving from/i)).toBeDefined();
  });

  test("safety warning comes first, and the user can still proceed (hard case)", async () => {
    api.createTrip.mockResolvedValue({
      trip_id: "t2",
      warnings: [{ kind: "safety", message: "Travel advisories warn against travel here." }],
    });
    api.proceedTrip.mockResolvedValue(undefined);
    render(<TripForm />);
    fillTokyo();
    fill(/^destination/i, "Kyiv, Ukraine");
    submit();

    expect(await screen.findByRole("heading", { name: /before you plan/i })).toBeDefined();
    expect(screen.getByText(/advisories warn against travel/i)).toBeDefined();
    expect(push).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Proceed anyway" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/trips/t2"));
    expect(api.proceedTrip).toHaveBeenCalledWith("t2");
  });

  test("the user can back out of a safety warning and keep their inputs", async () => {
    api.createTrip.mockResolvedValue({ trip_id: "t3", warnings: [{ kind: "safety", message: "Careful." }] });
    render(<TripForm />);
    fillTokyo();
    submit();
    fireEvent.click(await screen.findByRole("button", { name: "Change my trip" }));
    expect((screen.getByLabelText(/^destination/i) as HTMLInputElement).value).toBe("Tokyo, Japan");
    expect(api.proceedTrip).not.toHaveBeenCalled();
  });

  test("shows a server error", async () => {
    api.createTrip.mockRejectedValue(new Error("Can't reach the TravAI server."));
    render(<TripForm />);
    fillTokyo();
    submit();
    expect((await screen.findByRole("alert")).textContent).toMatch(/can't reach/i);
  });
});
