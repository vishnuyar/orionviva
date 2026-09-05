import { describe, expect, it } from "vitest";
import parity from "../../../../product/viva/surface/fixtures/overview-parity-v1.json";
import { adaptSpendingBreakdown } from "./spending";

function payload() {
  return {
    contract: "SpendingBreakdown.v1", state: "ready", title: "Spending breakdown",
    as_of: "2026-09-04", timezone_policy: "Inclusive local calendar dates.",
    period: { id: "latest_complete_month", label: "Last complete month · Aug 1–31", start_date: "2026-08-01", end_date: "2026-08-31" },
    granularity: "category", scope_summary: "All accounts · currencies shown separately",
    controls: {
      periods: [
        { id: "latest_complete_month", label: "Last complete month", requires_custom: false },
        { id: "current_month", label: "This month", requires_custom: false },
        { id: "last_3_months", label: "Last 3 months", requires_custom: false },
        { id: "year_to_date", label: "Year to date", requires_custom: false },
        { id: "custom", label: "Custom range", requires_custom: true },
      ],
      granularities: [{ id: "category", label: "Category" }, { id: "subcategory", label: "Subcategory" }],
      accounts: [{ id: "acct:usd", label: "Everyday", currency: "USD", order: 0 }, { id: "acct:eur", label: "Travel", currency: "EUR", order: 1 }],
      currencies: [{ id: "EUR", label: "EUR", order: 0 }, { id: "USD", label: "USD", order: 1 }],
      selected_period: "latest_complete_month", selected_granularity: "category", selected_account_id: "", selected_currency: "",
    },
    sections: [
      { currency: "EUR", order: 0, included_count: 1, total_display: "EUR 10.00", empty_message: "", bars: [{ id: "eur-food", order: 0, label: "food", amount_display: "EUR 10.00", share_basis_points: 10000, bar_basis_points: 10000, count: 1, color_token: "category-1" }] },
      { currency: "USD", order: 1, included_count: 2, total_display: "USD 3.00", empty_message: "", bars: [
        { id: "usd-food", order: 0, label: "food", amount_display: "USD 2.00", share_basis_points: 6667, bar_basis_points: 10000, count: 1, color_token: "category-1" },
        { id: "usd-rent", order: 1, label: "rent", amount_display: "USD 1.00", share_basis_points: 3333, bar_basis_points: 5000, count: 1, color_token: "category-2" },
      ] },
    ],
    coverage: { state: "partial", label: "Partial attested coverage.", covered_from: "2026-08-01", covered_to: "2026-08-31", gaps: [{ order: 0, account_id: "acct:eur", account_label: "Travel", from: "2026-08-16", to: "2026-08-31", reason: "missing_statement_coverage", sentence: "Travel has no attested statement coverage from 2026-08-16 through 2026-08-31." }], unsupported_accounts: [], included_count: 3, excluded_count: 1 },
    exclusions: [{ kind: "transfer", count: 1, sentence: "Transfers were excluded." }],
    notes: ["Currencies are separate."],
  };
}

describe("adaptSpendingBreakdown", () => {
  it("adapts the deterministic spending read from the real parity dispatch", () => {
    const artifact = parity as { today: string; reads: { spending: { result: { data: unknown } } } };
    const adapted = adaptSpendingBreakdown(artifact.reads.spending.result.data);
    expect(adapted?.asOf).toBe(artifact.today);
    expect(adapted?.contract).toBe("SpendingBreakdown.v1");
  });

  it("carries exact authored chart values without deriving display or width", () => {
    const adapted = adaptSpendingBreakdown(payload());
    expect(adapted?.sections[1].bars[1]).toMatchObject({
      order: 1, amountDisplay: "USD 1.00", shareBasisPoints: 3333,
      barBasisPoints: 5000, count: 1,
    });
    expect(adapted?.coverage.gaps[0].accountId).toBe("acct:eur");
  });

  it("keeps multiple missing account identities as ordered disclosures without fabricating IDs", () => {
    const raw: any = payload();
    raw.coverage.unsupported_accounts = [
      { order: 0, account_id: "", label: "First missing identity", currency: "USD", reason: "missing_account_id", sentence: "First missing identity has no stable account identity." },
      { order: 1, account_id: "", label: "Second missing identity", currency: "USD", reason: "missing_account_id", sentence: "Second missing identity has no stable account identity." },
      { order: 2, account_id: "acct:no-name", label: "No name", currency: "", reason: "missing_account_name", sentence: "No name has no account name." },
    ];
    const adapted = adaptSpendingBreakdown(raw);
    expect(adapted?.coverage.unsupportedAccounts.map((item) => [item.order, item.accountId, item.label])).toEqual([
      [0, "", "First missing identity"], [1, "", "Second missing identity"],
      [2, "acct:no-name", "No name"],
    ]);
  });

  it("accepts coherent counts at Number.MAX_SAFE_INTEGER", () => {
    const raw: any = payload();
    raw.controls.accounts = [raw.controls.accounts[1]];
    raw.controls.accounts[0].order = 0;
    raw.controls.currencies = [raw.controls.currencies[0]];
    raw.controls.selected_account_id = "acct:eur";
    raw.controls.selected_currency = "EUR";
    raw.sections = [raw.sections[0]];
    raw.sections[0].bars[0].count = Number.MAX_SAFE_INTEGER;
    raw.sections[0].included_count = Number.MAX_SAFE_INTEGER;
    raw.coverage.included_count = Number.MAX_SAFE_INTEGER;
    raw.exclusions[0].count = Number.MAX_SAFE_INTEGER;
    raw.coverage.excluded_count = Number.MAX_SAFE_INTEGER;

    expect(adaptSpendingBreakdown(raw)?.coverage).toMatchObject({
      includedCount: Number.MAX_SAFE_INTEGER,
      excludedCount: Number.MAX_SAFE_INTEGER,
    });
  });

  it.each(["included", "excluded"])("rejects coherent %s counts above Number.MAX_SAFE_INTEGER", (kind) => {
    const raw: any = payload();
    const unsafe = 2 ** 53;
    if (kind === "included") {
      raw.controls.accounts = [raw.controls.accounts[1]];
      raw.controls.accounts[0].order = 0;
      raw.controls.currencies = [raw.controls.currencies[0]];
      raw.controls.selected_account_id = "acct:eur";
      raw.controls.selected_currency = "EUR";
      raw.sections = [raw.sections[0]];
      raw.sections[0].bars[0].count = unsafe;
      raw.sections[0].included_count = unsafe;
      raw.coverage.included_count = unsafe;
    } else {
      raw.exclusions[0].count = unsafe;
      raw.coverage.excluded_count = unsafe;
    }
    expect(adaptSpendingBreakdown(raw)).toBeNull();
  });

  it.each([
    ["unknown top-level field", (raw: any) => { raw.derived_total = "13"; }],
    ["redundant raw total", (raw: any) => { raw.sections[1].total_exact = "4"; }],
    ["wrong share sum", (raw: any) => { raw.sections[1].bars[1].share_basis_points = 3332; }],
    ["redundant CSS width", (raw: any) => { raw.sections[1].bars[1].bar_width = "80.00%"; }],
    ["misordered bars", (raw: any) => { raw.sections[1].bars.reverse(); }],
    ["wrong bar ordinal", (raw: any) => { raw.sections[1].bars[1].order = 7; }],
    ["wrong section ordinal", (raw: any) => { raw.sections[1].order = 7; }],
    ["missing period option", (raw: any) => { raw.controls.periods.splice(2, 1); }],
    ["duplicate option", (raw: any) => { raw.controls.currencies.push(raw.controls.currencies[0]); }],
    ["account currency outside options", (raw: any) => { raw.controls.accounts[0].currency = "GBP"; }],
    ["unknown currency section", (raw: any) => { raw.sections[1].currency = "GBP"; }],
    ["inconsistent included count", (raw: any) => { raw.coverage.included_count = 4; }],
    ["inconsistent section count", (raw: any) => { raw.sections[1].included_count = 3; }],
    ["impossible calendar date", (raw: any) => { raw.period.start_date = "2026-02-31"; }],
    ["period after read date", (raw: any) => { raw.period.end_date = "2026-09-05"; }],
    ["complete coverage with a gap", (raw: any) => { raw.coverage.state = "complete"; }],
    ["gap outside period", (raw: any) => { raw.coverage.gaps[0].to = "2026-09-01"; }],
    ["overlapping authored gaps", (raw: any) => { raw.coverage.gaps.push({ ...raw.coverage.gaps[0], order: 1, from: "2026-08-20" }); }],
    ["unsupported account also selectable", (raw: any) => { raw.coverage.unsupported_accounts.push({ order: 0, account_id: "acct:usd", label: "Everyday", currency: "USD", reason: "missing_account_name", sentence: "Unsupported." }); }],
    ["fabricated missing account identity", (raw: any) => { raw.coverage.unsupported_accounts.push({ order: 0, account_id: "unsupported-1", label: "Missing", currency: "USD", reason: "missing_account_id", sentence: "Unsupported." }); }],
    ["claimed missing currency with a currency", (raw: any) => { raw.coverage.unsupported_accounts.push({ order: 0, account_id: "acct:no-money", label: "No money", currency: "USD", reason: "missing_account_currency", sentence: "Unsupported." }); }],
    ["null empty message", (raw: any) => { raw.sections[0].empty_message = null; }],
    ["boolean account order", (raw: any) => { raw.controls.accounts[0].order = false; }],
    ["boolean currency order", (raw: any) => { raw.controls.currencies[0].order = false; }],
    ["boolean section order", (raw: any) => { raw.sections[0].order = false; }],
    ["boolean bar order", (raw: any) => { raw.sections[0].bars[0].order = false; }],
    ["boolean gap order", (raw: any) => { raw.coverage.gaps[0].order = false; }],
    ["boolean unsupported order", (raw: any) => { raw.coverage.unsupported_accounts.push({ order: false, account_id: "acct:no-name", label: "No name", currency: "USD", reason: "missing_account_name", sentence: "Unsupported." }); }],
    ["boolean section count", (raw: any) => { raw.sections[0].included_count = true; }],
    ["boolean bar count", (raw: any) => { raw.sections[0].bars[0].count = true; }],
    ["boolean share basis points", (raw: any) => { raw.sections[0].bars[0].share_basis_points = true; }],
    ["boolean bar basis points", (raw: any) => { raw.sections[0].bars[0].bar_basis_points = true; }],
    ["boolean coverage included count", (raw: any) => { raw.coverage.included_count = true; }],
    ["boolean coverage excluded count", (raw: any) => { raw.coverage.excluded_count = true; }],
    ["boolean exclusion count", (raw: any) => { raw.exclusions[0].count = true; }],
    ["unknown exclusion", (raw: any) => { raw.exclusions[0].kind = "maybe"; }],
  ])("rejects %s", (_name, mutate) => {
    const raw = payload(); mutate(raw);
    expect(adaptSpendingBreakdown(raw)).toBeNull();
  });
});
