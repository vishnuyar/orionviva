import backendWire from "../../../../product/tests/fixtures/numerical_receipts/actual-backend-wire-v1.json";
import { describe, expect, it } from "vitest";
import { adaptTurn } from "./conversation";
import { conversationEvidenceFigure } from "../evidence";
const raw = { text: "A hypothetical result", question: "Suppose 10 dollars", answered: true, status: "answered", figures: [{ id: "f1", evidence_id: "conversation:t1:f1", written: "USD 10", value: "10", quantity: "balance", kind: "hypothetical", currency: "USD", dated: "2027-01-01", grade: "", boundary: {}, subject: null, receipt_ids: ["conversation:t1:numerical:0"], what: "Future balance", record_ids: [], evidence_links: [] }], numerical_receipts: [{ schema_version: 1, id: "conversation:t1:numerical:0", figure_ids: ["f1"], source_records: [], premises: [{ parameter: "opening", role: "starting_amount", raw: "10", modeled: "10.00", unit: "money", currency: "USD", source: "current_question", quote: "10 dollars", derivation: null }], observed_inputs: [], local_inputs: [], context: [], caveats: [] }] };
describe("typed numerical receipt delivery", () => {
  it("preserves scalar value, hypothetical date, empty grade and current-question premises without fabricating a document", () => {
    const figure = adaptTurn(raw)!.figures[0];
    expect(figure).toMatchObject({ numerical: { value: "10", kind: "hypothetical", grade: "", dated: "2027-01-01" }, receiptState: "ready", numericalReceipts: [{ premises: [{ quote: "10 dollars", modeled: "10.00" }] }] });
    const evidence = conversationEvidenceFigure(figure);
    expect(evidence.asOf).toEqual({ state: "supplied", value: "2027-01-01" });
    expect(evidence.evidenceLinks).toEqual([]);
  });
  it("preserves local and mixed source kinds instead of turning every record into a document", () => {
    const receipt = { ...raw.numerical_receipts[0], source_records: [{ record_id: "goal-event", kind: "local_activity", document_id: null }, { record_id: "movement", kind: "movement", document_id: "a".repeat(64) }], local_inputs: [{ event_id: "goal-event", event_type: "GoalCreated", fields: [{ label: "Target amount", value: "500" }] }] };
    expect(adaptTurn({ ...raw, figures: [{ ...raw.figures[0], record_ids: ["goal-event", "movement"] }], numerical_receipts: [receipt] })!.figures[0]).toMatchObject({ receiptState: "ready", numericalReceipts: [{ sourceRecords: [{ kind: "local_activity", documentId: null }, { kind: "movement", documentId: "a".repeat(64) }] }] });
  });
});

it("limits each selected figure to its own source and local lineage within a shared producing tool receipt", () => {
  const figures = [{ ...raw.figures[0], record_ids: ["local-a"] }, { ...raw.figures[0], id: "f2", evidence_id: "conversation:t1:f2", record_ids: ["local-b"] }];
  const shared = { ...raw.numerical_receipts[0], figure_ids: ["f1", "f2"], source_records: [{ record_id: "local-a", kind: "local_activity", document_id: null }, { record_id: "local-b", kind: "local_activity", document_id: null }], local_inputs: [{ event_id: "local-a", event_type: "GoalCreated", fields: [] }, { event_id: "local-b", event_type: "GoalCreated", fields: [] }] };
  const selected = adaptTurn({ ...raw, figures, numerical_receipts: [shared] })!.figures;
  expect(selected[0].numericalReceipts?.[0].sourceRecords.map((source) => source.recordId)).toEqual(["local-a"]);
  expect(selected[0].numericalReceipts?.[0].localInputs.map((input) => input.eventId)).toEqual(["local-a"]);
  expect(selected[1].numericalReceipts?.[0].sourceRecords.map((source) => source.recordId)).toEqual(["local-b"]);
});
it("accepts the closed subject variants without treating them as document targets", () => {
  for (const subject of [{ kind: "account", value: "Assets:Example" }, { grouping: "category" }, { account_id: "Assets:Example" }, { merchant: "Example Shop" }, { goal_id: "goal-example" }, null]) expect(adaptTurn({ ...raw, figures: [{ ...raw.figures[0], subject }] })!.figures[0].numerical?.subject).toEqual(subject);
});
it("marks malformed, unknown, cross-figure or quoted-from-another-question receipts unavailable without dropping the legacy answer", () => {
  for (const receipt of [{ ...raw.numerical_receipts[0], schema_version: 2 }, { ...raw.numerical_receipts[0], figure_ids: ["not-this-turn"] }, { ...raw.numerical_receipts[0], extra: "private" }, { ...raw.numerical_receipts[0], premises: [{ ...raw.numerical_receipts[0].premises[0], quote: "prior assistant supplied amount" }] }]) {
    const answer = adaptTurn({ ...raw, numerical_receipts: [receipt] })!;
    expect(answer.text).toBe(raw.text); expect(answer.figures[0].receiptState).toBe("unavailable");
  }
});

it("does not turn malformed typed data or hypothetical grade amplification into supported proof", () => {
  for (const changed of [{ grade: "verified" }, { value: 10 }, { quantity: "unknown_quantity" }, { boundary: { whole: "yes" } }, { subject: { grouping: "anything" } }]) {
    const figure = adaptTurn({ ...raw, figures: [{ ...raw.figures[0], ...changed }] })!.figures[0];
    expect(figure.receiptState).toBe("unavailable"); expect(figure.numerical).toBeUndefined();
    expect(conversationEvidenceFigure(figure).grade.grade).toBe("unavailable");
  }
});
it("never creates document navigation from local, unknown or malformed source records", () => {
  for (const source of [{ record_id: "local-a", kind: "local_activity", document_id: "a".repeat(64) }, { record_id: "unknown", kind: "external", document_id: "a".repeat(64) }, { record_id: "document", kind: "document", document_id: "not-a-captured-hash" }]) {
    const figure = adaptTurn({ ...raw, numerical_receipts: [{ ...raw.numerical_receipts[0], source_records: [source] }] })!.figures[0];
    expect(figure.receiptState).toBe("unavailable"); expect(conversationEvidenceFigure(figure).evidenceLinks).toEqual([]);
  }
});


it("retains typed receipts from all five genuine compiled backend wire examples", () => {
  expect(backendWire.examples).toHaveLength(5);
  for (const example of backendWire.examples) {
    const answer = adaptTurn(example.answer)!;
    expect(answer.figures).toHaveLength(example.answer.figures.length);
    for (const [index, figure] of answer.figures.entries()) {
      expect(figure.receiptState, `${example.case_id} figure ${index}`).toBe("ready");
      expect(figure.numerical?.value).toBe(example.answer.figures[index].value);
      expect(figure.numerical?.grade).toBe(example.answer.figures[index].grade);
      expect(figure.numerical?.dated).toBe(example.answer.figures[index].dated);
      expect(figure.numericalReceipts?.flatMap((receipt) => receipt.sourceRecords).every((source) => figure.recordIds.includes(source.recordId))).toBe(true);
      expect(conversationEvidenceFigure(figure).evidenceLinks.every((link) => figure.numericalReceipts?.some((receipt) => receipt.sourceRecords.some((source) => source.documentId === link.targetDocumentId)))).toBe(true);
    }
  }
});

it("rejects cross-turn receipt identities and undeclared local/context labels", () => {
  const cross = { ...raw.numerical_receipts[0], id: "conversation:another-turn:numerical:0" };
  const altered = [cross, { ...raw.numerical_receipts[0], context: [{ label: "Arbitrary provider error", value: "unreviewed" }] }, { ...raw.numerical_receipts[0], local_inputs: [{ event_id: "local", event_type: "UnknownEvent", fields: [] }] }];
  for (const receipt of altered) expect(adaptTurn({ ...raw, numerical_receipts: [receipt], figures: [{ ...raw.figures[0], receipt_ids: [receipt.id] }] })!.figures[0].receiptState).toBe("unavailable");
});


it("refuses repeated receipt references and duplicate source identities", () => {
  const duplicate = { ...raw.numerical_receipts[0], source_records: [{ record_id: "local", kind: "local_activity", document_id: null }, { record_id: "local", kind: "local_activity", document_id: null }] };
  expect(adaptTurn({ ...raw, numerical_receipts: [duplicate] })!.figures[0].receiptState).toBe("unavailable");
  expect(adaptTurn({ ...raw, figures: [{ ...raw.figures[0], receipt_ids: [raw.numerical_receipts[0].id, raw.numerical_receipts[0].id] }] })!.figures[0].receiptState).toBe("unavailable");
});


it("refuses an unsupported subject endpoint while retaining real boundary period endpoints", () => {
  const figure = { ...raw.figures[0], subject: { kind: "period", value: "2026-01-01", to: "2026-01-31" } };
  expect(adaptTurn({ ...raw, figures: [figure] })!.figures[0].receiptState).toBe("unavailable");
  const boundary = { whole: false, selected: [{ kind: "period", value: "2026-01-01", to: "2026-01-31" }] };
  expect(adaptTurn({ ...raw, figures: [{ ...raw.figures[0], boundary }] })!.figures[0].numerical?.boundary).toEqual(boundary);
});


it("uses the existing closed subject kind vocabulary without imposing boundary span rules", () => {
  for (const kind of ["account", "category", "merchant", "period", "since", "until", "subcategory", "tag", "currency", "kind"]) {
    const subject = { kind, value: "selected identity" };
    expect(adaptTurn({ ...raw, figures: [{ ...raw.figures[0], subject }] })!.figures[0].numerical?.subject).toEqual(subject);
  }
  expect(adaptTurn({ ...raw, figures: [{ ...raw.figures[0], subject: { kind: "unknown", value: "selected identity" } }] })!.figures[0].receiptState).toBe("unavailable");
});
