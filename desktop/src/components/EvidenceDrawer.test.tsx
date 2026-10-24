import { render, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { EvidenceDrawer } from "./EvidenceDrawer";
import type { SurfaceSnapshot, TurnFigure } from "../surface/types";
const doc = "a".repeat(64);
const selected = "conversation:t1:f1";
function snapshot(typed = true): SurfaceSnapshot {
  const figure: TurnFigure = { id: "f1", evidenceId: selected, written: "USD 10.00", what: "Example balance", grade: "verified", dated: "2026-01-31", recordIds: [doc], evidenceLinks: [{ targetDocumentId: doc, label: "Example statement", relation: "attests", page: "" }], ...(typed ? { numerical: { value: "10.00", quantity: "balance", kind: "financial", currency: "USD", dated: "2026-01-31", grade: "verified", boundary: { whole: true }, subject: null }, receiptState: "ready", numericalReceipts: [{ id: "conversation:t1:numerical:0", figureIds: ["f1"], sourceRecords: [{ recordId: doc, kind: "document", documentId: doc }], premises: [{ parameter: "initial_amount", role: "starting amount", raw: "10", modeled: "10.00", unit: "money", currency: "USD", source: "current_question", quote: "10 dollars", derivation: "decimal_numeric" }], observedInputs: [], localInputs: [], context: [], caveats: ["Only the recorded period is included."] }] } : {}) };
  return { disclosure: { title: "Private vault", subtitle: "Opened", detail: "" }, overview: { state: "absent", reason: "not requested" }, documents: { state: "ready", data: { documents: [{ id: doc, name: "example.txt", state: "Saved", phaseLabel: "", detail: "", source: "", pages: "", provenance: "", evidenceLinks: [] }], readingSentence: "", captureQueue: [], processingJobs: [], outboundRecords: [] } }, activity: { state: "absent", reason: "not requested" }, conversation: { state: "ready", data: { turns: [{ id: "t1", kind: "ask", occurredAt: "", prompt: "10 dollars", said: "", questionId: "", outcome: "completed", message: "", reason: "", answer: { question: "10 dollars", text: "Example answer", answered: true, status: "answered", outcomeTag: "", refusal: "", grade: "verified", gradeSentence: "", figures: [figure], options: [], missing: [], spoken: { maySpeak: false, withheld: "", parts: [], text: "", gradeSentence: "", citationSentence: "", localOnly: "" } }, proposal: null }], questions: { queue: [], count: 0, meta: { total: 0, tail: null, pending: null, invite: "", answeredByDocument: "" } } } }, trust: { state: "absent", reason: "not requested" } };
}
function draw(typed = true) { const onDismiss = vi.fn(); const onOpenDocument = vi.fn(); const view = render(<EvidenceDrawer snapshot={snapshot(typed)} selection={{ figureId: selected }} onDismiss={onDismiss} onOpenDocument={onOpenDocument} renderEvidenceBadge={(grade) => <span>{grade.label}</span>} />); return { ...view, onDismiss, onOpenDocument }; }
describe("supported typed figure evidence", () => {
  it("uses the actual quantity/date and meaningful limitations without contradictory legacy absence placeholders", () => {
    const view = draw();
    for (const text of ["Measurement type was not supplied by this read.", "Exactness unavailable", "Coverage was not supplied by this read.", "Provenance details were not supplied by this read."]) expect(view.queryByText(text)).toBeNull();
    expect(view.getByRole("heading", { name: "Figure details" })).toBeVisible(); expect(view.queryByRole("heading", { name: "Typed numerical figure" })).toBeNull();
    expect(view.container.querySelector('[data-field="quantity"]')).toHaveTextContent("Balance"); expect(view.container.querySelector('[data-field="dated"]')).toHaveTextContent("2026-01-31");
    expect(view.getByText("Only the recorded period is included.")).toBeVisible(); expect(view.container.querySelector(".record-identity-list")).toBeNull();
  });
  it("places a real source action before lengthy assumptions and retains keyboard access to source and close", async () => {
    const user = userEvent.setup(); const view = draw();
    const source = view.getByRole("button", { name: "Open example.txt" }); const assumptions = view.getByRole("heading", { name: "Current-question assumptions" });
    expect(source.compareDocumentPosition(assumptions) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    source.focus(); expect(source).toHaveFocus(); await user.keyboard("{Enter}"); expect(view.onOpenDocument).toHaveBeenCalledOnce();
    const close = view.getByRole("button", { name: "Close evidence" }); close.focus(); await user.keyboard("{Enter}"); expect(view.onDismiss).toHaveBeenCalledOnce();
  });
  it("leaves legacy figure details and document navigation unchanged", () => {
    const view = draw(false); expect(view.getByText("Measurement type was not supplied by this read.")).toBeVisible();
    fireEvent.click(view.getByRole("button", { name: "Open example.txt" })); expect(view.onOpenDocument).toHaveBeenCalledOnce();
  });
});
