import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { App } from "./App";

describe("minimal shell", () => {
  it("opens on the financial picture", () => {
    const { getByRole, getByText } = render(<App />);
    expect(getByRole("heading", { name: "Your financial picture" })).toBeInTheDocument();
    expect(getByText("$48,240.18")).toBeInTheDocument();
    expect(getByText("Corroborated · June 30, 2026")).toBeInTheDocument();
  });

  it("moves through shell destinations without leaving the page", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText } = render(<App />);
    await user.click(getByRole("button", { name: "DocumentsWhat supports it" }));
    expect(getByRole("heading", { name: "Documents" })).toBeInTheDocument();
    expect(getByText("Capture before reading")).toBeInTheDocument();
    expect(getByRole("heading", { name: "everyday-checking-june.pdf" })).toBeInTheDocument();
  });

  it("acknowledges document capture as local-only", async () => {
    const user = userEvent.setup();
    const { getByRole } = render(<App />);
    await user.click(getByRole("button", { name: /add document/i }));
    expect(getByRole("status")).toHaveTextContent("Nothing has left this device.");
  });

  it("keeps review count visible as a pending state", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText } = render(<App />);
    await user.click(getByRole("button", { name: "ReviewWhat needs you2" }));
    expect(getByRole("heading", { name: "2 questions are waiting" })).toBeInTheDocument();
    expect(getByText(/A proposal will always wait for an explicit yes/)).toBeInTheDocument();
  });

  it("shows the selected document detail inside documents", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText } = render(<App />);
    await user.click(getByRole("button", { name: "DocumentsWhat supports it" }));
    await user.click(getByRole("button", { name: /brokerage-may\.pdf/i }));
    expect(getByText("Scanner import")).toBeInTheDocument();
    expect(getByText("12 pages")).toBeInTheDocument();
  });

  it("shows the selected queue item inside review", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText } = render(<App />);
    await user.click(getByRole("button", { name: "ReviewWhat needs you2" }));
    await user.click(getByRole("button", { name: /merchant category/i }));
    expect(getByText("Merchant")).toBeInTheDocument();
    expect(getByText("Card purchase on Jun 24")).toBeInTheDocument();
  });
});
