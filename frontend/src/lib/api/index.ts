import type { TravaiApi } from "./client";
import { httpApi } from "./http";
import { createMockApi } from "./mock";

export { ApiError, type TravaiApi } from "./client";

/**
 * NEXT_PUBLIC_API_MOCK=true swaps the backend for an in-browser mock with
 * made-up prices, so the UI can be built before the endpoints exist. The
 * layout shows a "demo data" banner whenever it's on.
 */
export const USE_MOCK_API = process.env.NEXT_PUBLIC_API_MOCK === "true";

export const api: TravaiApi = USE_MOCK_API ? createMockApi() : httpApi;
