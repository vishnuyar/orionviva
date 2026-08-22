import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { AccountView, FeatureResult, OverviewData } from "../../surface/types";
import { Accounts } from "./Accounts";

const account = (id: string, name = `Account ${id}`, kind = "Depository"): AccountView => ({ id, name, kind, measure: "balance", exactValue: "", currency: "USD", display: "$10.00", grade: "unavailable", gradeLabel: "Evidence status unavailable", gradeDescription: "This read did not provide a recognized evidence grade.", note: null, asOf: "", coverage: null, provenance: null, evidenceLinks: [], state: "ready" });
const overview = (accounts: AccountView[]): OverviewData => ({ picture: { coverage: "", readOn: "", figures: [], withheld: [], unplaced: [] }, accounts });
const ready = (accounts: AccountView[]): FeatureResult<OverviewData> => ({ state: "ready", data: overview(accounts) });
const baseProps = { selectedAccount: "", onSelectAccount: vi.fn(), onOpenEvidence: vi.fn(), onOpenFigure: vi.fn(), onExploreSample: vi.fn() };

describe("Accounts stable identity presentation", () => {
  const longId = "A deliberately long supplied truth value stays visible and wraps without truncation across supported narrow viewport boundaries.";
  it("groups blank and duplicate IDs and exposes controls and figures only for unique accounts", () => {
    const view = render(<Accounts {...baseProps} result={ready([account("", "Blank"), account(" ", "Also blank"), account("same", "Duplicate one"), account("same", "Duplicate two"), account("unique", "Unique")])} />);
    expect(view.getAllByText("Account identity unavailable")).toHaveLength(1);
    expect(view.getAllByText("Account identity conflicted")).toHaveLength(1);
    expect(view.getAllByText("same")).toHaveLength(1);
    expect(view.getAllByRole("button", { name: /Unique/i }).filter((button) => button.classList.contains("detail-row-button"))).toHaveLength(1);
    expect(view.container.querySelectorAll(".figure-trigger")).toHaveLength(2);
    expect(view.queryByRole("button", { name: /Blank|Duplicate/i })).not.toBeInTheDocument();
  });

  it("renders missing, conflicted, and no-selectable detail refusal headings with requested IDs", () => {
    const view = render(<Accounts {...baseProps} selectedAccount="missing" result={ready([account("present")])} />);
    expect(view.getByRole("heading", { name: "Selected account unavailable" })).toHaveAttribute("tabindex", "-1");
    expect(view.getByText("The selected account is no longer present in this accounts read.")).toBeInTheDocument();
    expect(view.getByText("missing")).toBeInTheDocument();
    view.rerender(<Accounts {...baseProps} selectedAccount="same" result={ready([account("same"), account("same")])} />);
    expect(view.getByRole("heading", { name: "Account selection unavailable" })).toHaveAttribute("tabindex", "-1");
    expect(view.getByText("More than one account uses the selected identity, so the interface will not choose between them.")).toBeInTheDocument();
    view.rerender(<Accounts {...baseProps} result={ready([account(""), account(" ")])} />);
    expect(view.getByText("This accounts read contains rows, but none has a unique nonblank account ID.")).toBeInTheDocument();
  });

  it("keeps duplicate labels with distinct IDs selectable and ordinary selection does not move focus", () => {
    const onSelectAccount = vi.fn();
    const view = render(<Accounts {...baseProps} onSelectAccount={onSelectAccount} result={ready([account("one", "Same"), account("two", "Same")])} />);
    const buttons = view.getAllByRole("button", { name: /Same/i }).filter((button) => button.classList.contains("detail-row-button"));
    expect(buttons).toHaveLength(2);
    buttons[1].focus();
    fireEvent.click(buttons[1]);
    expect(onSelectAccount).toHaveBeenCalledWith("two");
    expect(buttons[1]).toHaveFocus();
  });


  it("keeps duplicate labels with distinct 128-character IDs selected exactly after reorder", () => {
    const secondId = longId.slice(0, -1) + "!";
    expect(longId).toHaveLength(128);
    expect(secondId).toHaveLength(128);
    const values = [account(longId, "Same long label"), account(secondId, "Same long label")];
    const view = render(<Accounts {...baseProps} selectedAccount={secondId} result={ready(values)} />);
    const selected = view.getAllByRole("button", { name: /Same long label/i }).filter((button) => button.classList.contains("detail-row-button") && button.getAttribute("aria-pressed") === "true");
    expect(selected).toHaveLength(1);
    selected[0].focus();
    view.rerender(<Accounts {...baseProps} selectedAccount={secondId} result={ready([...values].reverse())} />);
    const selectedAfter = view.getAllByRole("button", { name: /Same long label/i }).filter((button) => button.classList.contains("detail-row-button") && button.getAttribute("aria-pressed") === "true");
    expect(selectedAfter).toHaveLength(1);
    expect(selectedAfter[0]).toHaveFocus();
    expect(view.getByRole("heading", { name: "Same long label" })).toBeInTheDocument();
  });

  it("bounds a conflicted 128-character ID without a Figure, proof, or selection action", () => {
    const view = render(<Accounts {...baseProps} selectedAccount={longId} result={ready([account(longId, "First"), account(longId, "Second")])} />);
    expect(view.getAllByText(longId)).toHaveLength(2);
    expect(view.getByText("Account identity conflicted")).toBeInTheDocument();
    expect(view.getByRole("heading", { name: "Account selection unavailable" })).toBeInTheDocument();
    expect(view.queryByRole("button")).not.toBeInTheDocument();
  });
});
