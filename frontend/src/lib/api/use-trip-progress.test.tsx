import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import type { TripProgress } from "../types";
import { GIVE_UP_AFTER_MS, POLL_INTERVAL_MS, STALL_AFTER_MS, useTripProgress } from "./use-trip-progress";

const { api } = vi.hoisted(() => ({ api: { getProgress: vi.fn() } }));
vi.mock("./index", async () => {
  const { ApiError } = await import("./client");
  return { api, ApiError };
});

const researching = (steps: number): TripProgress => ({
  status: "researching",
  steps: Array.from({ length: steps }, (_, i) => ({ message: `step ${i}`, at: "2026-11-22T00:00:00Z" })),
});

/** Lets pending promises settle, then moves the clock. */
async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  api.getProgress.mockReset();
});
afterEach(() => vi.useRealTimers());

describe("useTripProgress", () => {
  test("polls until done, then stops", async () => {
    api.getProgress
      .mockResolvedValueOnce(researching(1))
      .mockResolvedValueOnce(researching(2))
      .mockResolvedValue({ status: "done", steps: researching(3).steps });
    const { result } = renderHook(() => useTripProgress("t1"));
    await advance(0);
    expect(result.current.progress?.steps).toHaveLength(1);
    await advance(POLL_INTERVAL_MS * 3);
    expect(result.current.progress?.status).toBe("done");
    const calls = api.getProgress.mock.calls.length;
    await advance(POLL_INTERVAL_MS * 5);
    expect(api.getProgress.mock.calls.length).toBe(calls);
  });

  test("says it's slow when nothing changes, then gives up, and retry starts again", async () => {
    api.getProgress.mockResolvedValue(researching(2));
    const { result } = renderHook(() => useTripProgress("t1"));
    await advance(0);
    expect(result.current.stalled).toBe(false);

    await advance(STALL_AFTER_MS + POLL_INTERVAL_MS);
    expect(result.current.stalled).toBe(true);
    expect(result.current.timedOut).toBe(false);

    await advance(GIVE_UP_AFTER_MS);
    expect(result.current.timedOut).toBe(true);
    const calls = api.getProgress.mock.calls.length;
    await advance(POLL_INTERVAL_MS * 5);
    expect(api.getProgress.mock.calls.length).toBe(calls);

    act(() => result.current.retry());
    await advance(0);
    expect(result.current.timedOut).toBe(false);
    expect(result.current.stalled).toBe(false);
    expect(api.getProgress.mock.calls.length).toBe(calls + 1);
  });

  test("a new step resets the slow timer", async () => {
    let steps = 1;
    api.getProgress.mockImplementation(async () => researching(steps));
    const { result } = renderHook(() => useTripProgress("t1"));
    await advance(STALL_AFTER_MS - 10_000);
    steps = 2;
    await advance(20_000);
    expect(result.current.stalled).toBe(false);
  });

  test("keeps retrying after a network error, but not after a 404", async () => {
    const { ApiError } = await import("./client");
    api.getProgress.mockRejectedValueOnce(new Error("offline")).mockResolvedValue(researching(1));
    const { result, unmount } = renderHook(() => useTripProgress("t1"));
    await advance(0);
    expect(result.current.error).toBe("offline");
    await advance(POLL_INTERVAL_MS);
    expect(result.current.error).toBeNull();
    expect(result.current.progress?.steps).toHaveLength(1);
    unmount();

    api.getProgress.mockReset();
    api.getProgress.mockRejectedValue(new ApiError("Trip not found", 404));
    const missing = renderHook(() => useTripProgress("nope"));
    await advance(0);
    expect(missing.result.current.error).toBe("Trip not found");
    await advance(POLL_INTERVAL_MS * 5);
    expect(api.getProgress).toHaveBeenCalledTimes(1);
  });
});
