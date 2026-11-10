/**
 * Base URL of the FastAPI backend. Every request to the backend goes through
 * this, so there is one place to change it.
 *
 * NEXT_PUBLIC_ variables are inlined into the browser bundle, so only put
 * public values here. API keys (LLM, flights, etc.) belong in the backend.
 */
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
