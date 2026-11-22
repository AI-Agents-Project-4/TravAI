"use client";

import { useEffect, useState } from "react";
import type { TripProgress } from "../types";
import { api } from "./index";

export const POLL_INTERVAL_MS = 1500;

export type ProgressState = {
  progress: TripProgress | null;
  error: string | null;
};

/**
 * Research/planning progress for a trip.
 *
 * Polling vs. SSE is still undecided (docs/api-contract.md), so this is the
 * only place that knows the transport. Today it polls `GET /trips/{id}/progress`
 * until the trip is done or failed.
 */
export function useTripProgress(tripId: string): ProgressState {
  const [state, setState] = useState<ProgressState>({ progress: null, error: null });

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function poll() {
      try {
        const progress = await api.getProgress(tripId);
        if (cancelled) return;
        setState({ progress, error: null });
        if (progress.status === "done" || progress.status === "failed") return;
      } catch (e) {
        if (cancelled) return;
        setState((s) => ({ ...s, error: e instanceof Error ? e.message : "Couldn't load progress." }));
      }
      timer = setTimeout(poll, POLL_INTERVAL_MS);
    }

    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [tripId]);

  return state;
}
