import { API_BASE_URL } from "../config";
import type { Plan, RedraftRequest } from "../types";
import { ApiError, type TravaiApi } from "./client";

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError("Can't reach the TravAI server. Is the backend running?", 0);
  }
  if (!response.ok) {
    let message = `The server returned an error (${response.status}).`;
    try {
      const data = (await response.json()) as { detail?: unknown };
      if (typeof data.detail === "string") message = data.detail;
    } catch {
      // Not JSON; keep the generic message.
    }
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const id = encodeURIComponent;

/** Talks to the FastAPI backend at API_BASE_URL. */
export const httpApi: TravaiApi = {
  createTrip: (body) => request("POST", "/trips", body),
  proceedTrip: async (tripId) => {
    await request<unknown>("POST", `/trips/${id(tripId)}/proceed`);
  },
  getProgress: (tripId) => request("GET", `/trips/${id(tripId)}/progress`),
  getPlans: (tripId) => request("GET", `/trips/${id(tripId)}/plans`),
  redraftPlan: (planId, body: RedraftRequest) =>
    request("POST", `/plans/${id(planId)}/redraft`, body),
  savePlan: (plan: Plan) => request("PUT", `/plans/${id(plan.id)}`, plan),
  getPlan: (planId) => request("GET", `/plans/${id(planId)}`),
};
