import { fireEvent, render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { AccountView, FeatureResult, OverviewData } from "../../surface/types";
import { Accounts } from "./Accounts";

const account = (id: string, name = `Account ${id}`, kind = "Depository"): AccountView => ({ id, name, maskedNumber: "", kind, measure: "balance", exactValue: "", currency: "USD", display: "$10.00", grade: "unavailable", gradeLabel: "Evidence status unavailable", gradeDescription: "This read did not provide a recognized evidence grade.", proofPresentation: { emphasis: "required", reasons: ["test"], qualifications: ["A reviewed qualification."] }, note: null, asOf: "", coverage: null, provenance: null, evidenceLinks: [], state: "ready" });
const overview = (accounts: AccountView[]): OverviewData => ({ picture: { coverage: "", readOn: "", figures: [], withheld: [], unplaced: [] }, accounts });
const ready = (accounts: AccountView[]): FeatureResult<OverviewData> => ({ state: "ready", data: overview(accounts) });
const baseProps = { selectedAccount: "", showVerificationDetails: false, onSelectAccount: vi.fn(), onOpenEvidence: vi.fn(), onOpenFigure: vi.fn(), onExploreSample: vi.fn() };

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
    expect(view.getByRole("heading", { name: "Accounts in this read" })).toHaveAttribute("tabindex", "-1");
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

  it("keeps each account opener a full nonshrinking row target and activates its exact ID from the keyboard", async () => {
    const user = userEvent.setup();
    const onSelectAccount = vi.fn();
    const onOpenAccount = vi.fn();
    const view = render(<Accounts {...baseProps} onSelectAccount={onSelectAccount} onOpenAccount={onOpenAccount} result={ready([account("one", "Everyday Checking"), account("two", "Rainy Day Savings")])} />);
    const target = view.getAllByRole("button", { name: /Rainy Day Savings/i }).find((button) => button.classList.contains("detail-row-button"))!;
    expect(target.closest(".account-detail-row")).not.toBeNull();
    expect(target).toHaveAttribute("data-account-id", "two");
    target.focus();
    await user.keyboard("{Enter}");
    expect(onSelectAccount).toHaveBeenCalledWith("two");
    expect(onOpenAccount).toHaveBeenCalledWith("two");
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

  it("applies routine and required proof generically while keeping caveats and the drawer trigger", () => {
    const routine = { ...account("routine", "Routine account"), grade: "conflicted" as const, gradeLabel: "Backend routine label", gradeDescription: "Backend routine description", proofPresentation: { emphasis: "routine" as const, reasons: [], qualifications: [] }, note: "Backend routine description", caveats: [] };
    const required = { ...account("required", "Required account"), grade: "verified" as const, gradeLabel: "Backend required label", gradeDescription: "Backend required description", proofPresentation: { emphasis: "required" as const, reasons: ["machine-only"], qualifications: ["A required backend qualification."] }, note: "Backend required description", caveats: ["A caveat that never recedes."] };
    const view = render(<Accounts {...baseProps} selectedAccount="routine" showVerificationDetails={false} result={ready([routine, required])} />);

    expect(view.queryByText("Backend routine label")).not.toBeInTheDocument();
    expect(view.queryByText("Backend routine description")).not.toBeInTheDocument();
    expect(view.getByText("A caveat that never recedes.")).toBeInTheDocument();
    expect(view.getByText("A required backend qualification.")).toBeInTheDocument();
    const requiredRow = view.getAllByRole("button", { name: /Required account/ }).find((button) => button.classList.contains("detail-row-button"));
    expect(requiredRow).toHaveTextContent("Backend required description");
    const triggers = view.getAllByRole("button", { name: "$10.00 Routine account balance" });
    expect(triggers).toHaveLength(2);
    triggers.forEach((trigger) => trigger.click());
    expect(baseProps.onOpenFigure).toHaveBeenNthCalledWith(1, "account:routine");
    expect(baseProps.onOpenFigure).toHaveBeenNthCalledWith(2, "account:routine");

    view.rerender(<Accounts {...baseProps} selectedAccount="routine" showVerificationDetails result={ready([routine, required])} />);
    expect(view.getAllByText("Backend routine description").length).toBeGreaterThan(0);
    expect(view.queryByText("machine-only")).not.toBeInTheDocument();
  });
});
