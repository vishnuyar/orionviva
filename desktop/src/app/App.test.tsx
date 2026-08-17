import { fireEvent, render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { App } from "./App";

describe("minimal shell", () => {
  it("opens on the financial picture", () => {
    const { getByRole, getByText } = render(<App />);
    expect(getByRole("heading", { name: "Your financial picture" })).toBeInTheDocument();
    expect(getByText("$48,240.18")).toBeInTheDocument();
    expect(getByText("Corroborated · July 31, 2026")).toBeInTheDocument();
  });

  it("moves through shell destinations without leaving the page", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText } = render(<App />);
    await user.click(getByRole("button", { name: "DocumentsWhat supports it" }));
    expect(getByRole("heading", { name: "Documents" })).toBeInTheDocument();
    expect(getByText("Capture before reading")).toBeInTheDocument();
    expect(getByRole("heading", { name: "silverline-checking-2026-07.pdf" })).toBeInTheDocument();
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
    await user.click(getByRole("button", { name: /fidelity-brokerage-2026-05-to-2026-07\.pdf/i }));
    expect(getByText("Generated locally")).toBeInTheDocument();
    expect(getByText("2 pages")).toBeInTheDocument();
  });

  it("shows the selected queue item inside review", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText } = render(<App />);
    await user.click(getByRole("button", { name: "ReviewWhat needs you2" }));
    await user.click(getByRole("button", { name: /merchant category/i }));
    expect(getByText("Merchant")).toBeInTheDocument();
    expect(getByText("Card purchase on Jun 24")).toBeInTheDocument();
  });

  it("keeps the selected document when navigation moves away and back", async () => {
    const user = userEvent.setup();
    const { getByRole } = render(<App />);

    await user.click(getByRole("button", { name: /documents.*what supports it/i }));
    await user.click(getByRole("button", { name: /fidelity-brokerage-2026-05-to-2026-07\.pdf/i }));
    expect(getByRole("heading", { name: "fidelity-brokerage-2026-05-to-2026-07.pdf" })).toBeInTheDocument();

    await user.click(getByRole("button", { name: /overview.*your picture/i }));
    await user.click(getByRole("button", { name: /documents.*what supports it/i }));
    expect(getByRole("heading", { name: "fidelity-brokerage-2026-05-to-2026-07.pdf" })).toBeInTheDocument();
    expect(getByRole("button", { name: /open page review/i })).toBeInTheDocument();
  });

  it("keeps the selected review question when navigation moves away and back", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText } = render(<App />);

    await user.click(getByRole("button", { name: /review.*what needs you2/i }));
    await user.click(getByRole("button", { name: /merchant category/i }));
    expect(getByText("Card purchase on Jun 24")).toBeInTheDocument();

    await user.click(getByRole("button", { name: /trust.*how it works/i }));
    await user.click(getByRole("button", { name: /review.*what needs you2/i }));
    expect(getByText("Card purchase on Jun 24")).toBeInTheDocument();
    expect(getByRole("button", { name: /open document review/i })).toBeInTheDocument();
  });

  it("lets the local capture notice be dismissed", async () => {
    const { getByRole, queryByRole } = render(<App />);

    fireEvent.click(getByRole("button", { name: /add document/i }));
    expect(getByRole("status")).toHaveTextContent("Nothing has left this device.");

    fireEvent.click(getByRole("button", { name: /dismiss notice/i }));
    expect(queryByRole("status")).not.toBeInTheDocument();
  });

  it("renders the trust surface as explicit local guarantees", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText } = render(<App />);

    await user.click(getByRole("button", { name: /trust.*how it works/i }));
    expect(getByRole("heading", { name: "Trust" })).toBeInTheDocument();
    expect(getByText("Local by default", { selector: "strong" })).toBeInTheDocument();
    expect(getByText("No silent inference", { selector: "strong" })).toBeInTheDocument();
    expect(getByText("Anchoring status", { selector: "strong" })).toBeInTheDocument();
  });
});
