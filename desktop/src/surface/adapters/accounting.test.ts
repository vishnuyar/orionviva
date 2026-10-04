import { describe, expect, it } from "vitest";
import { adaptAccounting } from "./accounting";

describe("accounting adapter", () => {
  it("preserves backend display values, hierarchy and separate evidence", () => {
    const view = adaptAccounting({ balance_sheet: { as_of: "2026-09-30", complete: true, display_by_currency: { AAA: { assets: "Backend assets" } }, lines: [] }, profit_loss: { start: "2026-09-01", end: "2026-09-30", complete: false, display_by_currency: { AAA: { net: "Backend net" }, BBB: { net: "Another currency" } }, lines: [{ movement_key: "m-1", display: "Exact backend formatting", provisional: true, amount_evidence: { provenance: "Statement evidence" }, classification_evidence: { reason: "Inferred purpose", by: "model" } }], hierarchy_tree: [{ currency: "AAA", roots: [{ label: "Expenses", display: "Backend subtotal", children: [{ label: "Household", display: "Category subtotal", children: [{ label: "Supplies", display: "Minor subtotal", children: [{ label: "Example Shop", display: "Merchant subtotal", children: [] }] }] }] }] }] } })!;
    expect(view.profitTotals.map((row) => row.currency)).toEqual(["AAA", "BBB"]);
    expect(view.profitTotals[0].values.net).toBe("Backend net");
    expect(view.lines[0]).toMatchObject({ display: "Exact backend formatting", amountEvidence: "Statement evidence", classificationEvidence: "Inferred purpose", provisional: true });
    expect(view.lines[0].classifiedBy).toBe("Viva's interpretation");
    expect(view.hierarchy[0].roots[0].children[0].children[0].children[0].label).toBe("Example Shop");
  });
  it("withholds absent contracts", () => {
    expect(adaptAccounting(null)).toBeUndefined();
    expect(adaptAccounting({ balance_sheet: {} })).toBeUndefined();
  });
});

it("uses the captured document allowlist and retains the explanation rather than its internal reason", () => {
  const view = adaptAccounting({ balance_sheet: { lines: [] }, profit_loss: { lines: [{ movement_key: "m-1", document_ids: ["captured-1"], proves: "accounting-claim", amount_evidence: { grade: "corroborated", provenance: { doc_id: "unlisted-document" } }, classification_evidence: { reason: "merchant_prior", explanation: "This merchant provides household supplies.", by: "merchant_prior", source_refs: ["accounting-claim"] } }] } })!;
  expect(view.lines[0].documentIds).toEqual(["captured-1"]);
  expect(view.lines[0].classificationEvidence).toBe("This merchant provides household supplies.");
  expect(view.lines[0].classifiedBy).toBe("Merchant knowledge");
  expect(view.lines[0].amountEvidence).toBe("Supported by more than one source or matching record.");
});

it("presents reason enums as readable accounting explanations", () => {
  const view = adaptAccounting({ balance_sheet: {}, profit_loss: { lines: [{ classification_evidence: { reason: "default" } }, { classification_evidence: { reason: "linked" } }, { classification_evidence: { reason: "ruling" } }] } })!;
  expect(view.lines.map((line) => line.classificationEvidence)).toEqual(["Ordinary income or expense interpretation", "Matched movement between accounts", "Recorded accounting treatment"]);
});

it("retains both a user's existing explanation and conflicting document components", () => {
  const view = adaptAccounting({ balance_sheet: {}, profit_loss: { unresolved_components: [{ document_ids: ["payroll-document"], classification_evidence: { reason: "conflicting_user_treatment", existing_treatment: { said: "This was a gift." } }, supporting_components: [{ account: "Income:Salary", display: "AAA -90" }] }] } })!;
  expect(view.unresolved[0]).toMatchObject({ existingExplanation: "This was a gift.", classificationEvidence: "The supporting document disagrees with your recorded accounting treatment", supportingComponents: [{ label: "Income:Salary", display: "AAA -90" }], documentIds: ["payroll-document"] });
});

it("retains precise missing balance explanations from the balance sheet payload", () => {
  const view = adaptAccounting({ balance_sheet: { missing: [
    { account: "Liabilities:ExampleLoan", why: "cash paid does not tell us the balance owed", reason: "Fallback reason" },
    { account: "Assets:ExampleEquipment", why: "the amount allocated to this asset is not recorded" },
    { account: "Assets:Other", reason: "A supporting valuation is unavailable" },
  ] }, profit_loss: {} })!;
  expect(view.missing).toEqual([
    { label: "Liabilities:ExampleLoan", reason: "cash paid does not tell us the balance owed" },
    { label: "Assets:ExampleEquipment", reason: "the amount allocated to this asset is not recorded" },
    { label: "Assets:Other", reason: "A supporting valuation is unavailable" },
  ]);
});
