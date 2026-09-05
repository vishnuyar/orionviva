import type { AccountLedgerData, AccountLedgerMovement, ActivityData } from "../../surface/types";

function movement(id: string, date: string, description: string, categoryId: string, categoryLabel: string, subcategoryId: string, subcategoryLabel: string): AccountLedgerMovement {
  return {
    id, date, description, account: "acct:checking", accountId: "acct:checking", accountName: "Everyday Checking \u2022\u2022\u2022\u20224417",
    direction: "out", directionDisplay: "Debit", exactValue: "12.00", currency: "USD", display: "$12.00", nature: "spending",
    treatment: { kind: "spending", name: "" }, loanRepaymentChoices: [], sentence: "", decidedBy: "default",
    provisional: false, linked: false,
    category: { id: categoryId, label: categoryLabel, valid: true },
    subcategory: { id: subcategoryId, label: subcategoryLabel, valid: true },
    classification: { grade: "unverified", provenance: "merchant taxonomy" }, classificationValid: true,
    tags: id === "movement:c" ? [{ id: "travel", label: "Travel" }] : [], tagsValid: true,
    evidenceLinks: [{ targetDocumentId: "april", label: "april.pdf", relation: "attests", page: "2", region: `row:${id}` }], evidenceLinksValid: true,
    transfer: id === "movement:c" ? { state: "suggested", explanation: "A possible linked account movement.", candidates: [{ id: "movement:savings", date: "2026-04-19", description: "Possible transfer from checking", account: "acct:savings", accountId: "acct:savings", accountName: "Rainy Day Savings", direction: "in", exactValue: "12.00", currency: "USD", display: "$12.00", relationship: "The vault found the corresponding movement in Rainy Day Savings." }], complete: true, limit: 20 } : { state: "none" },
    actions: [], deduplication: { state: "single", canonicalMovementId: id, memberMovementIds: [id] },
  };
}

export const ledger: AccountLedgerData = {
  scope: { kind: "account", accountId: "acct:checking" }, revision: "revision-one",
  account: { id: "acct:checking", name: "Everyday Checking", maskedNumber: "\u2022\u2022\u2022\u20224417", type: "depository", currency: "USD", balance: { state: "available", kind: "current_balance", exactValue: "300", display: "$300.00", asOf: "2026-04-30", grade: "corroborated" } },
  coverage: { state: "gapped", runs: [{ from: "2026-01-01", to: "2026-02-28", statementIds: ["january", "february"] }, { from: "2026-04-01", to: "2026-04-30", statementIds: ["april"] }], gaps: [{ from: "2026-03-01", to: "2026-03-31", reason: "missing_statement_coverage" }] },
  reconciliation: { balance: "reconciled", overlap: { state: "none_observed", deduplication: { state: "none", policy: "exact_economic_posting_in_overlapping_statements_only", collapsed: [], unresolved: [] }, groups: [] }, runningBalance: { state: "absent", reason: "not_authoritatively_available" } },
  sources: [{ documentId: "april", accountId: "acct:checking", filename: "april.pdf", relation: "statement_and_movement_evidence", period: { from: "2026-04-01", to: "2026-04-30" } }],
  groups: [
    { month: "2026-04", label: "April 2026", movements: [movement("movement:c", "2026-04-18", "Possible transfer to savings", "dining", "Dining", "restaurant", "Restaurant"), movement("movement:b", "2026-04-17", "Corner market", "groceries", "Groceries", "supermarket", "Supermarket")] },
    { month: "2026-02", label: "February 2026", movements: [movement("movement:a", "2026-02-12", "Neighborhood cafe", "dining", "Dining", "restaurant", "Restaurant")] },
  ],
  page: { limit: 50, returned: 3, remaining: 0, nextCursor: null },
};

export const activity: ActivityData = {
  sentence: "Activity", movements: [], beyond: { count: 0 },
  vocabularies: {
    categories: { items: [{ id: "dining", label: "Dining" }, { id: "groceries", label: "Groceries" }], complete: true, limit: 40 },
    subcategories: { items: [{ id: "restaurant", label: "Restaurant", categoryId: "dining" }, { id: "supermarket", label: "Supermarket", categoryId: "groceries" }], complete: true, limit: 200 },
    tags: { items: [{ id: "travel", label: "Travel" }], complete: true, limit: 40, maxSelected: 40, maxLabelLength: 80 },
  },
};
