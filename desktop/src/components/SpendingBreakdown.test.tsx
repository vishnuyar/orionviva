import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { FeatureResult, SpendingBreakdownData } from "../surface/types";
import { SpendingBreakdown } from "./SpendingBreakdown";

function data(label = "groceries", overrides: Partial<SpendingBreakdownData> = {}): SpendingBreakdownData {
  return {
    contract: "SpendingBreakdown.v1", state: "ready", title: "Spending breakdown", asOf: "2026-09-04",
    timezonePolicy: "Local dates; inclusive.",
    period: { id: "latest_complete_month", label: "Last complete month · Aug 1–Aug 31", startDate: "2026-08-01", endDate: "2026-08-31" },
    granularity: "category", scopeSummary: "All available accounts · currencies shown separately",
    controls: {
      periods: [{ id: "latest_complete_month", label: "Last complete month", requiresCustom: false }, { id: "current_month", label: "This month", requiresCustom: false }, { id: "custom", label: "Custom range", requiresCustom: true }],
      granularities: [{ id: "category", label: "Category" }, { id: "subcategory", label: "Subcategory" }],
      accounts: [{ id: "acct:one", label: "Everyday", currency: "USD", order: 0 }], currencies: [{ id: "USD", label: "USD", order: 0 }],
      selectedPeriod: "latest_complete_month", selectedGranularity: "category", selectedAccountId: "", selectedCurrency: "",
    },
    sections: [{ currency: "USD", order: 0, includedCount: 2, totalDisplay: "USD 125.00", emptyMessage: "", bars: [{ id: `bar-${label}`, order: 0, label, amountDisplay: "USD 125.00", shareBasisPoints: 10000, barBasisPoints: 3750, count: 2, colorToken: "category-1" }] }],
    coverage: { state: "partial", label: "Partial attested statement coverage; uncovered dates are excluded.", coveredFrom: "2026-08-01", coveredTo: "2026-08-31", includedCount: 2, excludedCount: 1, gaps: [{ order: 0, accountId: "acct:one", accountLabel: "Everyday", from: "2026-08-20", to: "2026-08-21", reason: "missing_statement_coverage", sentence: "Everyday has no attested statement coverage from Aug 20 through Aug 21." }], unsupportedAccounts: [] },
    exclusions: [{ kind: "transfer", count: 1, sentence: "Own-account transfers were excluded." }], notes: ["No cross-currency total is used."], ...overrides,
  };
}
const ready = (value: SpendingBreakdownData): FeatureResult<SpendingBreakdownData> => ({ state: "ready", data: value });

describe("SpendingBreakdown", () => {
  it("requests the default and renders authored text, accessibility, and width", async () => {
    const read = vi.fn(async () => ready(data()));
    const view = render(<SpendingBreakdown read={read} />);

    expect(await screen.findByRole("listitem", { name: "groceries: USD 125.00; 2 included movements" })).toBeInTheDocument();
    expect(read).toHaveBeenCalledWith({ period: "latest_complete_month", granularity: "category" });
    expect(view.container.querySelector(".spending-bar-fill")?.getAttribute("width")).toBe("3750");
    expect(screen.getAllByText("USD 125.00")).toHaveLength(2);
    expect(screen.getByText(/Partial attested statement coverage/)).toBeInTheDocument();
    expect(screen.getByText("Everyday has no attested statement coverage from Aug 20 through Aug 21.")).toBeInTheDocument();
  });

  it("retains the prior authored chart while an update fails", async () => {
    let resolveUpdate: ((result: FeatureResult<SpendingBreakdownData>) => void) | undefined;
    const read = vi.fn()
      .mockResolvedValueOnce(ready(data("old category")))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveUpdate = resolve; }));
    render(<SpendingBreakdown read={read} />);
    await screen.findByText("old category");

    await userEvent.selectOptions(screen.getByLabelText("Spending breakdown granularity"), "subcategory");
    expect(screen.getByText("old category")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("previous selection remains below");
    await act(async () => resolveUpdate?.({ state: "failed", reason: "read_failed" }));
    expect(screen.getByText("old category")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("could not be read");
  });

  it("prevents dependent account changes until the authored scope returns", async () => {
    let release: ((result: FeatureResult<SpendingBreakdownData>) => void) | undefined;
    let releaseAll: ((result: FeatureResult<SpendingBreakdownData>) => void) | undefined;
    const choices = data("initial", { controls: { ...data().controls, accounts: [
      { id: "acct:usd", label: "Everyday", currency: "USD", order: 0 },
      { id: "acct:eur", label: "Travel", currency: "EUR", order: 1 },
    ], currencies: [{ id: "EUR", label: "EUR", order: 0 }, { id: "USD", label: "USD", order: 1 }] } });
    const read = vi.fn()
      .mockResolvedValueOnce(ready(choices))
      .mockImplementationOnce(() => new Promise((resolve) => { release = resolve; }))
      .mockImplementationOnce(() => new Promise((resolve) => { releaseAll = resolve; }))
      .mockResolvedValueOnce(ready(data("EUR result", {
        controls: { ...choices.controls, accounts: [{ id: "acct:eur", label: "Travel", currency: "EUR", order: 0 }], currencies: [{ id: "EUR", label: "EUR", order: 0 }], selectedAccountId: "acct:eur" },
        scopeSummary: "Travel · EUR",
      })));
    render(<SpendingBreakdown read={read} />);
    await screen.findByText("initial");

    const scope = screen.getByLabelText("Spending account scope");
    await userEvent.selectOptions(scope, "acct:usd");
    expect(scope).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByLabelText("Spending currency")).toHaveAttribute("aria-disabled", "true");
    await userEvent.selectOptions(scope, "acct:eur");
    expect(read).toHaveBeenCalledTimes(2);
    await act(async () => release?.(ready(data("USD result", {
      controls: { ...choices.controls, accounts: [{ id: "acct:usd", label: "Everyday", currency: "USD", order: 0 }], currencies: [{ id: "USD", label: "USD", order: 0 }], selectedAccountId: "acct:usd" },
      scopeSummary: "Everyday · USD",
    }))));
    expect(await screen.findByText("USD result")).toBeInTheDocument();
    expect(screen.getByLabelText("Spending account scope")).toHaveAttribute("aria-disabled", "false");
    await userEvent.selectOptions(screen.getByLabelText("Spending account scope"), "");
    expect(screen.getByLabelText("Spending account scope")).toHaveAttribute("aria-disabled", "true");
    await act(async () => releaseAll?.(ready(choices)));
    await screen.findByText("initial");
    await userEvent.selectOptions(screen.getByLabelText("Spending account scope"), "acct:eur");
    await waitFor(() => expect(read).toHaveBeenLastCalledWith({ period: "latest_complete_month", granularity: "category", accountId: "acct:eur" }));
  });

  it("does not let an old reader overwrite a newer vault generation", async () => {
    let releaseOld: ((result: FeatureResult<SpendingBreakdownData>) => void) | undefined;
    const oldRead = vi.fn()
      .mockResolvedValueOnce(ready(data("initial vault")))
      .mockImplementationOnce(() => new Promise((resolve) => { releaseOld = resolve; }));
    const newRead = vi.fn(async () => ready(data("new vault")));
    const view = render(<SpendingBreakdown read={oldRead} />);
    await screen.findByText("initial vault");
    await userEvent.selectOptions(screen.getByLabelText("Spending breakdown granularity"), "subcategory");

    view.rerender(<SpendingBreakdown read={newRead} />);
    expect(await screen.findByText("new vault")).toBeInTheDocument();
    await act(async () => releaseOld?.(ready(data("stale vault"))));
    expect(screen.queryByText("stale vault")).not.toBeInTheDocument();
    expect(screen.getByText("new vault")).toBeInTheDocument();
  });

  it("sends custom bounds only with a custom period", async () => {
    const read = vi.fn(async () => ready(data()));
    render(<SpendingBreakdown read={read} />);
    await screen.findByText("groceries");
    await userEvent.selectOptions(screen.getByLabelText("Spending date range"), "custom");
    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-08-03" } });
    fireEvent.change(screen.getByLabelText("End date"), { target: { value: "2026-08-17" } });
    await userEvent.click(screen.getByRole("button", { name: "Apply dates" }));
    await waitFor(() => expect(read).toHaveBeenLastCalledWith(expect.objectContaining({ period: "custom", startDate: "2026-08-03", endDate: "2026-08-17" })));
  });

  it("keeps multiple currencies in separately labelled figures", async () => {
    const usd = data().sections[0];
    const read = vi.fn(async () => ready(data("groceries", {
      controls: { ...data().controls, accounts: [
        { id: "acct:one", label: "Everyday", currency: "USD", order: 0 },
        { id: "acct:two", label: "Travel", currency: "EUR", order: 1 },
      ], currencies: [{ id: "EUR", label: "EUR", order: 0 }, { id: "USD", label: "USD", order: 1 }] },
      sections: [
        { currency: "EUR", order: 0, includedCount: 1, totalDisplay: "EUR 40.00", emptyMessage: "", bars: [{ id: "eur-travel", order: 0, label: "travel", amountDisplay: "EUR 40.00", shareBasisPoints: 10000, barBasisPoints: 10000, count: 1, colorToken: "category-1" }] },
        { ...usd, order: 1 },
      ],
      coverage: { ...data().coverage, includedCount: 3 },
    })));
    render(<SpendingBreakdown read={read} />);

    expect(await screen.findByRole("list", { name: "EUR spending, EUR 40.00 total" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "USD spending, USD 125.00 total" })).toBeInTheDocument();
    expect(screen.getByLabelText("Spending currency")).toHaveValue("");
    expect(screen.queryByText(/combined total/i)).not.toBeInTheDocument();
  });

  it("renders authored empty and locked states without an invented chart", async () => {
    const empty = data("unused", {
      state: "empty",
      sections: [{ currency: "USD", order: 0, includedCount: 0, totalDisplay: "USD 0.00", emptyMessage: "No eligible spending is attested for this selection.", bars: [] }],
      coverage: { ...data().coverage, includedCount: 0 },
    });
    const emptyView = render(<SpendingBreakdown read={async () => ready(empty)} />);
    expect(await screen.findByText("No eligible spending is attested for this selection.")).toBeInTheDocument();
    expect(emptyView.container.querySelector(".spending-bar-fill")).toBeNull();
    emptyView.unmount();

    render(<SpendingBreakdown read={async () => ({ state: "absent", reason: "locked" })} />);
    expect(await screen.findByText("Spending breakdown is locked")).toBeInTheDocument();
  });
});
