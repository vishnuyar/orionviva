import { describe, expect, it } from "vitest";
import { adaptAccountLedger } from "./account-ledger";

const movement = (id: string, date: string, accountId = "acct:checking") => ({
  id, date, description: id, account: accountId, account_id: accountId,
  account_name: "Everyday Checking \u2022\u2022\u2022\u20224417", direction: "out",
  direction_display: "Debit",
  exact_value: "12.00", currency: "USD", display: "$12.00",
  nature: "spending", treatment: { kind: "spending", name: "" },
  loan_repayment_choices: [], sentence: "", decided_by: "default",
  provisional: false, linked: false,
  category: { id: null, label: "uncategorized" },
  subcategory: { id: null, label: "" }, classification: null, tags: [],
  evidence_links: [{ document_id: "april", label: "april.pdf", relation: "attests", page: "2", region: `row:${id}` }],
  transfer: { state: "none" }, actions: [],
  deduplication: { state: "single", canonical_movement_id: id, member_movement_ids: [id] },
});

const payload = () => ({
  state: "ready",
  scope: { kind: "account", account_id: "acct:checking" },
  revision: "revision-one",
  account: { id: "acct:checking", name: "Everyday Checking", number_masked: "\u2022\u2022\u2022\u20224417", type: "depository", currency: "USD",
    balance: { state: "available", kind: "current_balance", exact_value: "300", display: "$300.00", as_of: "2026-04-30", grade: "corroborated" } },
  coverage: { state: "gapped", runs: [
    { from: "2026-01-01", to: "2026-02-28", statement_ids: ["january", "february", "overlap"] },
    { from: "2026-04-01", to: "2026-04-30", statement_ids: ["april"] },
  ], gaps: [{ from: "2026-03-01", to: "2026-03-31", reason: "missing_statement_coverage" }] },
  reconciliation: { balance: "reconciled", overlap: { state: "overlap_present", deduplication: {
    state: "none", policy: "exact_economic_posting_in_overlapping_statements_only", collapsed: [], unresolved: [],
  }, groups: [
    { from: "2026-02-15", to: "2026-02-28", document_ids: ["february", "overlap"] },
  ] }, running_balance: { state: "absent", reason: "not_authoritatively_available" } },
  sources: [
    { document_id: "april", account_id: "acct:checking", filename: "april.pdf", relation: "statement_and_movement_evidence", period: { from: "2026-04-01", to: "2026-04-30" } },
    { document_id: "february", account_id: "acct:checking", filename: "february.pdf", relation: "statement", period: { from: "2026-02-01", to: "2026-02-28" } },
    { document_id: "january", account_id: "acct:checking", filename: "january.pdf", relation: "statement", period: { from: "2026-01-01", to: "2026-01-31" } },
    { document_id: "overlap", account_id: "acct:checking", filename: "overlap.pdf", relation: "statement", period: { from: "2026-02-15", to: "2026-02-28" } },
  ],
  groups: [{ month: "2026-04", label: "April 2026", movements: [movement("movement:c", "2026-04-18"), movement("movement:b", "2026-04-18")] }],
  page: { limit: 2, returned: 2, remaining: 1, next_cursor: "opaque" },
});

describe("AccountLedger.v1 adapter", () => {
  it("keeps backend grouping, account scope, coverage, overlap, evidence, and movement order", () => {
    const read = adaptAccountLedger(payload());
    expect(read?.scope).toEqual({ kind: "account", accountId: "acct:checking" });
    expect(read?.groups[0].movements.map((row) => row.id)).toEqual(["movement:c", "movement:b"]);
    expect(read?.coverage.gaps[0]).toEqual({ from: "2026-03-01", to: "2026-03-31", reason: "missing_statement_coverage" });
    expect(read?.reconciliation.overlap.deduplication.state).toBe("none");
    expect(read?.reconciliation.runningBalance.state).toBe("absent");
    expect(read?.groups[0].movements[0].evidenceLinks[0].region).toBe("row:movement:c");
    expect(read?.groups[0].movements[0].directionDisplay).toBe("Debit");
    expect(read?.groups[0].movements.every((row) => row.actions.length === 0)).toBe(true);
  });

  it("requires the backend-authored debit, credit, or unavailable direction display", () => {
    const credit = payload(); credit.groups[0].movements[0].direction = "in"; credit.groups[0].movements[0].direction_display = "Credit";
    expect(adaptAccountLedger(credit)?.groups[0].movements[0].directionDisplay).toBe("Credit");
    const unavailable = payload(); unavailable.groups[0].movements[0].direction_display = "Direction unavailable";
    expect(adaptAccountLedger(unavailable)?.groups[0].movements[0].directionDisplay).toBe("Direction unavailable");
    const invented = payload(); invented.groups[0].movements[0].direction_display = "Charge";
    expect(adaptAccountLedger(invented)).toBeNull();
    const missing = payload(); delete (missing.groups[0].movements[0] as Partial<ReturnType<typeof movement>> & { direction_display?: string }).direction_display;
    expect(adaptAccountLedger(missing)).toBeNull();
  });

  it("accepts a transaction-only ledger with an explicitly absent balance", () => {
    const raw = payload();
    (raw.account as { balance: unknown }).balance = { state: "absent", reason: "no_authoritative_balance_observation" };
    raw.reconciliation.balance = "not_established";
    const read = adaptAccountLedger(raw);
    expect(read?.account.balance).toEqual({ state: "absent", reason: "no_authoritative_balance_observation" });
    expect(read?.groups[0].movements).toHaveLength(2);
  });

  it("fails atomically on unsafe identity, account leakage, duplicate IDs, reordering, or an invented running balance", () => {
    const unmasked = payload(); unmasked.account.number_masked = "000000004417";
    expect(adaptAccountLedger(unmasked)).toBeNull();

    const leaked = payload(); leaked.groups[0].movements[0] = movement("movement:c", "2026-04-18", "acct:savings");
    expect(adaptAccountLedger(leaked)).toBeNull();

    const duplicate = payload(); duplicate.groups[0].movements[1] = movement("movement:c", "2026-04-18");
    expect(adaptAccountLedger(duplicate)).toBeNull();

    const reordered = payload(); reordered.groups[0].movements = [movement("movement:b", "2026-04-18"), movement("movement:c", "2026-04-18")];
    expect(adaptAccountLedger(reordered)).toBeNull();

    const running = payload() as ReturnType<typeof payload> & { running_balance?: string };
    running.running_balance = "$288.00";
    expect(adaptAccountLedger(running)).toBeNull();
  });

  it("rejects actions, malformed evidence, unbound sources, and other-account source claims", () => {
    const action = payload(); (action.groups[0].movements[0] as { actions: string[] }).actions = ["assign_meaning"];
    expect(adaptAccountLedger(action)).toBeNull();

    const malformedEvidence = payload(); malformedEvidence.groups[0].movements[0].evidence_links[0].relation = "mentions";
    expect(adaptAccountLedger(malformedEvidence)).toBeNull();

    const evidenceOutsideSources = payload(); evidenceOutsideSources.groups[0].movements[0].evidence_links[0].document_id = "other-account-doc";
    expect(adaptAccountLedger(evidenceOutsideSources)).toBeNull();

    const unreferencedSource = payload(); (unreferencedSource.sources as unknown[]).push({
      document_id: "other-account-doc", account_id: "acct:checking", filename: "april.pdf",
      relation: "movement_evidence", period: null,
    });
    expect(adaptAccountLedger(unreferencedSource)).toBeNull();

    const otherAccount = payload(); otherAccount.sources[0].account_id = "acct:savings";
    expect(adaptAccountLedger(otherAccount)).toBeNull();
  });

  it("requires exactly the missing intervals implied by normalized coverage runs", () => {
    const shifted = payload(); shifted.coverage.gaps[0].from = "2026-03-02";
    expect(adaptAccountLedger(shifted)).toBeNull();

    const missing = payload(); missing.coverage.gaps = [];
    expect(adaptAccountLedger(missing)).toBeNull();

    const extra = payload(); extra.coverage.gaps.push({
      from: "2026-05-01", to: "2026-05-02", reason: "missing_statement_coverage",
    });
    expect(adaptAccountLedger(extra)).toBeNull();
  });

  it("binds statement periods to the run and every overlap that names them", () => {
    const outsideRun = payload();
    outsideRun.sources.find((item) => item.document_id === "january")!.period = {
      from: "2025-12-01", to: "2026-01-31",
    };
    expect(adaptAccountLedger(outsideRun)).toBeNull();

    const missesOverlap = payload();
    missesOverlap.sources.find((item) => item.document_id === "overlap")!.period = {
      from: "2026-02-20", to: "2026-02-25",
    };
    expect(adaptAccountLedger(missesOverlap)).toBeNull();

    const fabricatedOverlap = payload();
    fabricatedOverlap.reconciliation.overlap.groups[0].from = "2026-02-16";
    expect(adaptAccountLedger(fabricatedOverlap)).toBeNull();

    const overlapOnly = payload();
    overlapOnly.coverage.runs[0].statement_ids = ["january", "february"];
    expect(adaptAccountLedger(overlapOnly)).toBeNull();
  });

  it("rejects unknown movement fields, including a per-row running balance", () => {
    const raw = payload();
    (raw.groups[0].movements[0] as Record<string, unknown>).running_balance = "$288.00";
    expect(adaptAccountLedger(raw)).toBeNull();
  });

  it("accepts only pagination states the backend can emit", () => {
    const empty = payload();
    empty.groups = [];
    empty.sources.find((item) => item.document_id === "april")!.relation = "statement";
    (empty as { page: unknown }).page = { limit: 2, returned: 0, remaining: 0, next_cursor: null };
    expect(adaptAccountLedger(empty)).not.toBeNull();

    const emptyWithMore = payload();
    emptyWithMore.groups = [];
    emptyWithMore.sources.find((item) => item.document_id === "april")!.relation = "statement";
    emptyWithMore.page = { limit: 2, returned: 0, remaining: 1, next_cursor: "opaque" };
    expect(adaptAccountLedger(emptyWithMore)).toBeNull();

    const partialWithMore = payload();
    partialWithMore.groups[0].movements = [movement("movement:c", "2026-04-18")];
    partialWithMore.page = { limit: 2, returned: 1, remaining: 1, next_cursor: "opaque" };
    expect(adaptAccountLedger(partialWithMore)).toBeNull();

    const emptyCursor = payload(); emptyCursor.page.next_cursor = "";
    emptyCursor.page.remaining = 0;
    expect(adaptAccountLedger(emptyCursor)).toBeNull();
  });

  it("rejects impossible dates, non-finite decimals, oversize pages, and unknown closed states", () => {
    const date = payload(); date.groups[0].movements[0].date = "2026-02-30";
    expect(adaptAccountLedger(date)).toBeNull();

    const balanceDate = payload(); balanceDate.account.balance.as_of = "2026-02-30";
    expect(adaptAccountLedger(balanceDate)).toBeNull();

    const decimal = payload(); decimal.groups[0].movements[0].exact_value = "Infinity";
    expect(adaptAccountLedger(decimal)).toBeNull();

    const page = payload(); page.page.limit = 101;
    expect(adaptAccountLedger(page)).toBeNull();

    const state = payload(); state.reconciliation.overlap.state = "maybe";
    expect(adaptAccountLedger(state)).toBeNull();
  });

  it("enforces balance kind from account type and the authoritative decimal sign", () => {
    const assetOwed = payload(); assetOwed.account.balance.kind = "amount_owed";
    expect(adaptAccountLedger(assetOwed)).toBeNull();

    const liability = payload(); liability.account.type = "liability";
    liability.account.balance.kind = "amount_owed";
    expect(adaptAccountLedger(liability)?.account.balance.state).toBe("available");

    const liabilityNegative = payload(); liabilityNegative.account.type = "liability";
    liabilityNegative.account.balance.exact_value = "-0.01";
    liabilityNegative.account.balance.kind = "current_balance";
    expect(adaptAccountLedger(liabilityNegative)?.account.balance.state).toBe("available");

    const liabilityWrong = payload(); liabilityWrong.account.type = "liability";
    liabilityWrong.account.balance.exact_value = "-0.01";
    liabilityWrong.account.balance.kind = "amount_owed";
    expect(adaptAccountLedger(liabilityWrong)).toBeNull();

    const liabilityNegativeZero = payload(); liabilityNegativeZero.account.type = "liability";
    liabilityNegativeZero.account.balance.kind = "amount_owed";
    liabilityNegativeZero.account.balance.exact_value = "-0.00e2";
    expect(adaptAccountLedger(liabilityNegativeZero)?.account.balance.state).toBe("available");
  });

  it("requires exact duplicate membership and unioned source evidence", () => {
    const raw = payload();
    const row = raw.groups[0].movements[0];
    raw.coverage.runs[1].statement_ids.push("april-overlap");
    raw.sources.push({ document_id: "april-overlap", account_id: "acct:checking", filename: "april-overlap.pdf", relation: "statement_and_movement_evidence", period: { from: "2026-04-10", to: "2026-04-30" } });
    raw.reconciliation.overlap.groups.push({ from: "2026-04-10", to: "2026-04-30", document_ids: ["april", "april-overlap"] });
    row.evidence_links.push({ document_id: "april-overlap", label: "april-overlap.pdf", relation: "attests", page: "4", region: "row:duplicate" });
    row.deduplication = { state: "exact_duplicate", canonical_movement_id: "movement:c", member_movement_ids: ["movement:c", "movement:z"] };
    const deduplication = {
      state: "exact_duplicates_collapsed", policy: "exact_economic_posting_in_overlapping_statements_only",
      collapsed: [{ canonical_movement_id: "movement:c", member_movement_ids: ["movement:c", "movement:z"], document_ids: ["april", "april-overlap"] }],
      unresolved: [],
    };
    (raw.reconciliation.overlap as { deduplication: unknown }).deduplication = deduplication;
    expect(adaptAccountLedger(raw)?.groups[0].movements[0].deduplication.state).toBe("exact_duplicate");

    deduplication.collapsed[0].document_ids = ["april"];
    expect(adaptAccountLedger(raw)).toBeNull();
  });
});
