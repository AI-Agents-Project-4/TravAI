import type {
  CreateTripResponse,
  Plan,
  PlansResponse,
  RedraftRequest,
  RedraftResponse,
  TripProgress,
  TripRequest,
} from "../types";

/** One method per endpoint in docs/api-contract.md. */
export interface TravaiApi {
  /** `POST /trips` */
  createTrip(request: TripRequest): Promise<CreateTripResponse>;
  /**
   * `POST /trips/{id}/proceed`: the user saw the safety warning and wants to
   * go ahead. PROPOSED in the contract's open question, not agreed yet.
   */
  proceedTrip(tripId: string): Promise<void>;
  /** `GET /trips/{id}/progress` */
  getProgress(tripId: string): Promise<TripProgress>;
  /** `GET /trips/{id}/plans` */
  getPlans(tripId: string): Promise<PlansResponse>;
  /** `POST /plans/{id}/redraft` */
  redraftPlan(planId: string, request: RedraftRequest): Promise<RedraftResponse>;
  /** `PUT /plans/{id}` */
  savePlan(plan: Plan): Promise<Plan>;
  /** `GET /plans/{id}` */
  getPlan(planId: string): Promise<Plan>;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
