import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { App } from "./App";

describe("minimal shell", () => {
  it("opens on the financial picture", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: "Your financial picture" })).toBeInTheDocument();
    expect(screen.getByText("$48,240.18")).toBeInTheDocument();
    expect(screen.getByText("Corroborated · June 30, 2026")).toBeInTheDocument();
  });

  it("moves through shell destinations without leaving the page", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: "Documents" }));
    expect(screen.getByRole("heading", { name: "Documents" })).toBeInTheDocument();
    expect(screen.getByText("Capture before reading")).toBeInTheDocument();
  });

  it("acknowledges document capture as local-only", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: /add document/i }));
    expect(screen.getByRole("status")).toHaveTextContent("Nothing has left this device.");
  });

  it("keeps review count visible as a pending state", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: /^Review/ }));
    expect(screen.getByRole("heading", { name: "2 questions are waiting" })).toBeInTheDocument();
    expect(screen.getByText(/A proposal will always wait for an explicit yes/)).toBeInTheDocument();
  });
});
