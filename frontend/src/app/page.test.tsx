import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import Home from "./page";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

test("home page renders the app name and the trip form", () => {
  render(<Home />);
  expect(screen.getByRole("heading", { level: 1, name: "TravAI" })).toBeDefined();
  expect(screen.getByRole("form", { name: "Plan a trip" })).toBeDefined();
});
