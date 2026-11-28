"use client";

import { useCallback, useEffect, useState } from "react";
import type { TripProgress } from "../types";
import { ApiError, api } from "./index";

export const POLL_INTERVAL_MS = 1500;
/** No new step for this long: tell the user it's slow, keep checking. */
export const STALL_AFTER_MS = 90_000;
/** No new step for this long: stop checking and let the user decide. */
export const GIVE_UP_AFTER_MS = 10 * 60_000;

export type ProgressState = {
  progress: TripProgress | null;
  /** Latest error from the server, if the last check failed. */
  error: string | null;
  /** Nothing new for STALL_AFTER_MS. Still checking. */
  stalled: boolean;
  /** Nothing new for GIVE_UP_AFTER_MS. Stopped checking until retry(). */
  timedOut: boolean;
  /** Start checking again after a timeout. */
  retry: () => void;
};

function fingerprint(p: TripProgress): string {
  return `${p.status}:${p.steps.length}`;
}

/**
 * Research/planning progress for a trip.
 *
 * Polling vs. SSE is still undecided (docs/api-contract.md), so this is the
 * only place that knows the transport. Today it polls `GET /trips/{id}/progress`
 * until the trip is done or failed, or nothing changes for GIVE_UP_AFTER_MS.
 */
export function useTripProgress(tripId: string): ProgressState {
  const [progress, setProgress] = useState<TripProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stalled, setStalled] = useState(false);
  const [timedOut, setTimedOut] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let lastPrint = "";
    let lastChange = Date.now();

    async function poll() {
      try {
        const next = await api.getProgress(tripId);
        if (cancelled) return;
        setProgress(next);
        setError(null);
        const print = fingerprint(next);
        if (print !== lastPrint) {
          lastPrint = print;
          lastChange = Date.now();
        }
        if (next.status === "done" || next.status === "failed") {
          setStalled(false);
          return;
        }
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Couldn't load progress.");
        // A missing trip won't appear by retrying.
        if (e instanceof ApiError && e.status === 404) return;
      }
      const quiet = Date.now() - lastChange;
      setStalled(quiet >= STALL_AFTER_MS);
      if (quiet >= GIVE_UP_AFTER_MS) {
        setTimedOut(true);
        return;
      }
      timer = setTimeout(poll, POLL_INTERVAL_MS);
    }

    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [tripId, attempt]);

  const retry = useCallback(() => {
    setTimedOut(false);
    setStalled(false);
    setAttempt((a) => a + 1);
  }, []);

  return { progress, error, stalled, timedOut, retry };
}
