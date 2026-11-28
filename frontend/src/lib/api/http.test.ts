import { expect, test } from "vitest";
import { errorDetail } from "./http";

test("reads FastAPI error bodies", () => {
  expect(errorDetail({ detail: "Trip not found" })).toBe("Trip not found");
  expect(
    errorDetail({ detail: [{ loc: ["body", "budget", "amount"], msg: "Input should be greater than 0" }] }),
  ).toBe("budget.amount: Input should be greater than 0");
  expect(errorDetail({ detail: [{ msg: "Bad request" }] })).toBe("Bad request");
  expect(errorDetail({ nope: true })).toBeNull();
  expect(errorDetail(null)).toBeNull();
});
