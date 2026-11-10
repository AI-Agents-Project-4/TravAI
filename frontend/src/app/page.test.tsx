import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import Home from "./page";

test("home page renders the app name", () => {
  render(<Home />);
  expect(
    screen.getByRole("heading", { level: 1, name: "TravAI" }),
  ).toBeDefined();
});
