import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AccountingReports } from "./AccountingReports";
import type { AccountingView } from "../surface/types";

const view: AccountingView = { asOf: "2026-09-30", start: "2026-09-01", end: "2026-09-30", balanceComplete: false, profitComplete: false, balanceTotals: [{ currency: "AAA", values: { assets: "AAA 101", liabilities: "AAA 22", net: "AAA 79" } }], profitTotals: [{ currency: "AAA", values: { income: "AAA 70", expenses: "AAA 17", net: "AAA 53", provisional_income: "AAA 70", provisional_expenses: "AAA 2" } }], balances: [], lines: [{ id: "m-1", label: "Example Shop", account: "Everyday", date: "2026-09-10", currency: "AAA", display: "AAA 17", provisional: true, amountEvidence: "Reconciled statement", classificationEvidence: "Ordinary expense fallback", classifiedBy: "inference", origin: "" }], unresolved: [{ id: "m-2", label: "Loan", account: "Everyday", date: "2026-09-11", currency: "AAA", display: "AAA 9", provisional: false, amountEvidence: "Reconciled statement", classificationEvidence: "Principal and interest allocation unavailable", classifiedBy: "", origin: "" }], missing: [{ label: "Loan", reason: "Opening balance unavailable" }], heldCount: 0, hierarchy: [] };

describe("accounting reports", () => {
  it("preserves backend totals and separates amount evidence from inferred meaning", () => {
    render(<AccountingReports report={view} />);
    expect(screen.getByRole("heading", { name: "Balance sheet" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Profit and loss" })).toBeTruthy();
    expect(screen.getByText("AAA 53")).toBeTruthy();
    expect(screen.getAllByText("Reconciled statement")[0]).toBeTruthy();
    expect(screen.getByText(/Ordinary expense fallback/)).toBeTruthy();
    expect(screen.getByText(/Principal and interest allocation unavailable/)).toBeTruthy();
    expect(screen.getByText(/Opening balance unavailable/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /review|confirm/i })).toBeNull();
  });
});

it("requests a selected period from the backend and keeps prior reports when the read fails", async () => {
  const { fireEvent, waitFor } = await import("@testing-library/react");
  const { vi } = await import("vitest");
  const accountingReader = vi.fn().mockResolvedValue({ state: "failed", code: "read_failed", message: "Unavailable" });
  render(<AccountingReports report={view} accountingReader={accountingReader} />);
  fireEvent.change(screen.getByLabelText("Period start"), { target: { value: "2026-09-05" } });
  fireEvent.click(screen.getByRole("button", { name: "Update period" }));
  await waitFor(() => expect(accountingReader).toHaveBeenCalledWith("2026-09-05", "2026-09-30"));
  await waitFor(() => expect(screen.getByRole("status").textContent).toContain("could not be updated"));
  expect(screen.getByText("AAA 53")).toBeTruthy();
});

it("opens the captured source behind a report line", async () => {
  const { fireEvent } = await import("@testing-library/react");
  const { vi } = await import("vitest");
  const onInspectDocument = vi.fn();
  render(<AccountingReports report={{ ...view, lines: [{ ...view.lines[0], documentIds: ["document-1"] }] }} onInspectDocument={onInspectDocument} />);
  fireEvent.click(screen.getByRole("button", { name: "View source" }));
  expect(onInspectDocument).toHaveBeenCalledWith("document-1");
});

it("preserves the selected period after a correction refresh and ignores an older report response", async () => {
  const { act, fireEvent, waitFor } = await import("@testing-library/react");
  const { vi } = await import("vitest");
  let resolveOld: (result: unknown) => void = () => undefined;
  const old = new Promise((resolve) => { resolveOld = resolve; });
  const refreshed = { ...view, start: "2026-09-05", profitTotals: [{ currency: "AAA", values: { net: "Corrected selected period" } }] };
  const accountingReader = vi.fn().mockReturnValueOnce(old).mockResolvedValueOnce({ state: "ready", data: refreshed });
  const rendered = render(<AccountingReports report={view} accountingReader={accountingReader} />);
  fireEvent.change(screen.getByLabelText("Period start"), { target: { value: "2026-09-05" } });
  fireEvent.click(screen.getByRole("button", { name: "Update period" }));
  rendered.rerender(<AccountingReports report={{ ...view, lines: [{ ...view.lines[0], classificationEvidence: "Corrected meaning" }] }} accountingReader={accountingReader} />);
  await waitFor(() => expect(accountingReader).toHaveBeenNthCalledWith(2, "2026-09-05", "2026-09-30"));
  await waitFor(() => expect(screen.getByText("Corrected selected period")).toBeTruthy());
  expect(screen.getByLabelText("Period start")).toHaveValue("2026-09-05");
  await act(async () => resolveOld({ state: "ready", data: view }));
  expect(screen.getByText("Corrected selected period")).toBeTruthy();
});

it("shows a payroll disagreement beside the user's explanation with document receipt access", async () => {
  const { fireEvent } = await import("@testing-library/react");
  const { vi } = await import("vitest");
  const onInspectDocument = vi.fn();
  render(<AccountingReports report={{ ...view, unresolved: [{ ...view.unresolved[0], existingExplanation: "This was a gift.", classificationEvidence: "The supporting document disagrees with your recorded accounting treatment", supportingComponents: [{ label: "Income:Salary", display: "AAA -90" }, { label: "Expenses:Withholding", display: "AAA 20" }], documentIds: ["payroll-document"] }] }} onInspectDocument={onInspectDocument} />);
  expect(screen.getByText("This was a gift.")).toBeTruthy();
  expect(screen.getByText("What the supporting document records")).toBeTruthy();
  expect(screen.getByText("AAA -90")).toBeTruthy();
  expect(screen.getByText("AAA 20")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "View source" }));
  expect(onInspectDocument).toHaveBeenCalledWith("payroll-document");
});
