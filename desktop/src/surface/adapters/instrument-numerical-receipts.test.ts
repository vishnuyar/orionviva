import actualTaxZeroResponse from "./fixtures/tax-zero-instrument-actual-response-v1.json";
import exactNegativeResponse from "./fixtures/exact-negative-instrument-actual-response-v1.json";
import actualRetirementResponse from "./fixtures/public-ret-c-actual-response-v1.json";
import { describe, expect, it } from "vitest";
import { adaptTurn } from "./conversation";

// Byte-for-byte public ActionOutcome produced by the provider-free real
// Vault/conversation/compiler/receipt route, not a hand-authored positive.
describe("actual C instrument numerical receipt contract", () => {
  it("retains the actual allocation and rounded percentage-point receipts separately", () => {
    const answer = adaptTurn(actualRetirementResponse.state)!;
    expect(answer.figures).toHaveLength(2);
    expect(answer.figures[0]).toMatchObject({ numerical: { quantity: "ratio_of_balance", value: "0.6835517528255877", kind: "financial", grade: "corroborated" }, receiptState: "ready" });
    expect(answer.figures[1]).toMatchObject({ numerical: { quantity: "allocation_percentage_points", value: "-1.64482472", kind: "hypothetical", grade: "" }, receiptState: "ready" });
  });
});

import dedicatedResponses from "./fixtures/dedicated-instrument-actual-responses-v1.json";
import { numericalFigure } from "./numerical-receipts";

it("retains all genuine compiled source-principal/source-rate and positive PP receipts", () => {
  expect(dedicatedResponses).toHaveLength(3);
  const quantities = new Set<string>();
  for (const response of dedicatedResponses) {
    const answer = adaptTurn(response.state)!;
    for (const [index, figure] of answer.figures.entries()) {
      quantities.add(figure.numerical?.quantity ?? "");
      expect(figure.receiptState).toBe("ready");
      expect(figure.numerical).toMatchObject({ value: response.state.figures[index].value, quantity: response.state.figures[index].quantity, kind: response.state.figures[index].kind, currency: response.state.figures[index].currency, grade: response.state.figures[index].grade });
    }
  }
  expect(quantities).toEqual(new Set(["deposit_contract_principal", "loan_original_principal", "instrument_rate", "ratio_of_balance", "allocation_percentage_points"]));
});

it("admits a leading plus only for closed ungraded percentage-point differences", () => {
  const point = actualRetirementResponse.state.figures[1];
  for (const value of ["+10", "-10", "0", "-1.64482472"]) expect(numericalFigure({ ...point, value })?.value).toBe(value);
  for (const value of ["+-10", "++10", "+", "+01", "+.5", "NaN", "Infinity", "1e2", " 10"]) expect(numericalFigure({ ...point, value })).toBeUndefined();
  for (const quantity of ["balance", "owed", "income", "ratio", "ratio_of_balance", "instrument_rate", "deposit_contract_principal", "loan_original_principal"]) {
    const financial = { ...point, quantity, kind: "financial", grade: "corroborated", currency: ["instrument_rate", "ratio", "ratio_of_balance"].includes(quantity) ? "" : "USD" };
    expect(numericalFigure({ ...financial, value: "+10" })).toBeUndefined();
  }
  const ordinary = { ...point, quantity: "balance", kind: "financial", grade: "corroborated", currency: "USD" };
  for (const value of ["10", "-10"]) expect(numericalFigure({ ...ordinary, value })?.value).toBe(value);
});

it("does not amplify PP into a bank-graded or monetary source quantity", () => {
  const point = actualRetirementResponse.state.figures[1];
  for (const change of [{ kind: "financial", grade: "verified" }, { kind: "computed" }, { kind: "activity" }, { grade: "corroborated" }, { currency: "USD" }]) expect(numericalFigure({ ...point, ...change })).toBeUndefined();
  for (const response of dedicatedResponses.slice(0, 2)) for (const figure of response.state.figures) {
    for (const change of [{ kind: "hypothetical", grade: "" }, { kind: "computed" }, { grade: "" }, { currency: figure.quantity === "instrument_rate" ? "USD" : "" }]) expect(numericalFigure({ ...figure, ...change })).toBeUndefined();
  }
});

it("refuses unknown quantity/context, extra receipt fields, and broken source identities", () => {
  const state = actualRetirementResponse.state;
  for (const quantity of ["instrument_rate_v2", "loan_remaining_principal", "Allocation_percentage_points"]) expect(numericalFigure({ ...state.figures[1], quantity })).toBeUndefined();
  for (const receipt of [
    { ...state.numerical_receipts[0], context: [...state.numerical_receipts[0].context, { label: "Provider numeric conclusion", value: "unreviewed" }] },
    { ...state.numerical_receipts[0], extra: "unreviewed" },
    { ...state.numerical_receipts[0], source_records: [{ record_id: "source", kind: "document", document_id: "not-a-captured-hash" }] },
  ]) expect(adaptTurn({ ...state, numerical_receipts: [receipt] })!.figures.every((figure) => figure.receiptState === "unavailable")).toBe(true);
});

it("admits only the exact reviewed tax absence context label without broadening context keys", () => {
  const state = actualRetirementResponse.state;
  const value = "For 2025-01-01 through 2025-01-31, sum of the complete accepted tax event set (no events).";
  const withLabel = (label: string) => ({ ...state, numerical_receipts: [{ ...state.numerical_receipts[0], context: [{ label, value }] }] });
  expect(adaptTurn(withLabel("Tax absence rule"))!.figures.every((figure) => figure.receiptState === "ready")).toBe(true);
  for (const label of ["Tax absence", "Tax absence rule ", "Tax Absence Rule", "Provider tax conclusion"]) expect(adaptTurn(withLabel(label))!.figures.every((figure) => figure.receiptState === "unavailable")).toBe(true);
});


it("retains the genuine exact negative comparison beside its financial source allocation", () => {
  const answer = adaptTurn(exactNegativeResponse.state)!;
  expect(answer.figures[0]).toMatchObject({ numerical: { quantity: "ratio_of_balance", value: "0.6", kind: "financial", grade: "corroborated" }, receiptState: "ready" });
  expect(answer.figures[1]).toMatchObject({ numerical: { quantity: "allocation_percentage_points", value: "-10", kind: "hypothetical", grade: "", currency: "" }, receiptState: "ready" });
});


it("retains the genuine monthly derived-zero receipt and its fixed reviewed absence context", () => {
  const answer = adaptTurn(actualTaxZeroResponse.state)!;
  expect(answer.figures[0]).toMatchObject({ numerical: { quantity: "spending", value: "0", kind: "financial", currency: "USD", grade: "corroborated" }, receiptState: "ready" });
  expect(answer.figures[0].numericalReceipts?.[0].context).toContainEqual({ label: "Tax absence rule", value: "For 2021-02-01 through 2021-02-28, sum of the complete accepted tax event set (no events)." });
});
